//! MusicBrainz ETL command-line entry point.
//!
//! The default invocation materializes PostgreSQL COPY tables into compact
//! JSONL projections. The `aggregate` subcommand joins those projections into
//! local evidence and vocabulary artifacts.

mod aggregate;
mod serve;

use std::collections::BTreeMap;
use std::ffi::OsString;
use std::fs::{self, File, OpenOptions};
use std::io::{self, BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use bzip2::read::BzDecoder;
use clap::Parser;
use serde::Serialize;
use sha2::{Digest, Sha256};
use tar::Archive;

const SCHEMA_VERSION: &str = "musicbrainz-etl-staging-v1";
const DEFAULT_SOURCE_URL: &str = "https://musicbrainz.org/doc/MusicBrainz_Database/Download";
const DEFAULT_ATTRIBUTION: &str = "MusicBrainz; derived instrumental-credit index.";
const DEFAULT_LICENSE: &str = "CC0";

#[derive(Debug, Parser)]
#[command(name = "musicbrainz-etl", about = "Materialize a MusicBrainz dump once")]
struct Args {
    /// Extracted mbdump directory or tar/tar.bz2 archive.
    dump: PathBuf,

    /// Empty directory where projected JSONL tables will be written.
    output: PathBuf,

    /// Version attached to every generated artifact.
    #[arg(long)]
    snapshot_version: String,

    #[arg(long, default_value = DEFAULT_SOURCE_URL)]
    source_url: String,

    #[arg(long, default_value = DEFAULT_LICENSE)]
    license: String,

    #[arg(long, default_value = DEFAULT_ATTRIBUTION)]
    attribution: String,

    /// Seconds between progress messages written to stderr.
    #[arg(long, default_value_t = 5.0, value_parser = positive_float)]
    progress_interval: f64,

    #[arg(long, help = "Disable progress output on stderr")]
    no_progress: bool,
}

#[derive(Debug, Clone, Copy)]
struct TableSpec {
    name: &'static str,
    columns: &'static [usize],
    required: bool,
}

const TABLE_SPECS: &[TableSpec] = &[
    TableSpec { name: "artist", columns: &[0, 1, 2], required: true },
    TableSpec { name: "artist_credit", columns: &[0, 1], required: false },
    TableSpec { name: "artist_credit_name", columns: &[0, 1, 2, 3], required: true },
    TableSpec { name: "instrument", columns: &[0, 1, 2], required: true },
    TableSpec { name: "link_type", columns: &[0, 6], required: true },
    TableSpec { name: "link", columns: &[0, 1], required: true },
    TableSpec { name: "link_attribute_type", columns: &[0, 4, 5], required: true },
    TableSpec { name: "link_attribute", columns: &[0, 1], required: true },
    TableSpec { name: "link_attribute_credit", columns: &[0, 1, 2], required: false },
    TableSpec { name: "l_artist_recording", columns: &[1, 2, 3], required: true },
    TableSpec { name: "l_artist_instrument", columns: &[1, 2, 3], required: false },
    TableSpec { name: "l_artist_release", columns: &[1, 2, 3], required: false },
    TableSpec { name: "recording", columns: &[0, 1, 2, 3], required: true },
    // MusicBrainz medium columns are id, release, position. Position is 2.
    TableSpec { name: "medium", columns: &[0, 1], required: false },
    TableSpec { name: "release", columns: &[0, 1, 2, 3], required: false },
    // Track columns are gid, recording, medium, position, number, title, ...
    TableSpec { name: "track", columns: &[1, 2, 3], required: true },
];

#[derive(Debug, Serialize)]
struct Manifest {
    schema_version: &'static str,
    snapshot_version: String,
    generated_at: String,
    source: &'static str,
    source_url: String,
    license: String,
    attribution: String,
    table_count: usize,
    row_count: u64,
    projected_bytes: u64,
    manifest_hash: String,
    tables: BTreeMap<String, TableManifest>,
}

#[derive(Debug, Serialize)]
struct TableManifest {
    columns: Vec<usize>,
    required: bool,
    rows: u64,
    bytes: u64,
    sha256: String,
}

struct TableOutput {
    writer: io::BufWriter<File>,
    digest: Sha256,
    bytes: u64,
    rows: u64,
}

impl TableOutput {
    fn create(path: &Path) -> io::Result<Self> {
        let file = OpenOptions::new().create_new(true).write(true).open(path)?;
        Ok(Self {
            writer: io::BufWriter::with_capacity(1024 * 1024, file),
            digest: Sha256::new(),
            bytes: 0,
            rows: 0,
        })
    }

    fn write_projected_row(&mut self, row: &[Option<String>]) -> Result<(), EtlError> {
        let mut encoded = serde_json::to_vec(row)?;
        encoded.push(b'\n');
        self.writer.write_all(&encoded)?;
        self.digest.update(&encoded);
        self.bytes += encoded.len() as u64;
        self.rows += 1;
        Ok(())
    }
}

#[derive(Debug)]
enum EtlError {
    Io(io::Error),
    Json(serde_json::Error),
    MissingTable(String),
    InvalidArgument(String),
    InvalidCopy(String),
}

impl std::fmt::Display for EtlError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "I/O error: {error}"),
            Self::Json(error) => write!(formatter, "JSON error: {error}"),
            Self::MissingTable(table) => write!(formatter, "required dump table is missing: {table}"),
            Self::InvalidArgument(message) => write!(formatter, "invalid argument: {message}"),
            Self::InvalidCopy(message) => write!(formatter, "invalid PostgreSQL COPY row: {message}"),
        }
    }
}

impl std::error::Error for EtlError {}

impl From<io::Error> for EtlError {
    fn from(error: io::Error) -> Self { Self::Io(error) }
}

impl From<serde_json::Error> for EtlError {
    fn from(error: serde_json::Error) -> Self { Self::Json(error) }
}

struct Progress {
    enabled: bool,
    interval: Duration,
    started: Instant,
    last_report: Instant,
    table: String,
    rows: u64,
}

impl Progress {
    fn new(enabled: bool, interval_seconds: f64) -> Self {
        let now = Instant::now();
        Self {
            enabled,
            interval: Duration::from_secs_f64(interval_seconds),
            started: now,
            last_report: now,
            table: String::new(),
            rows: 0,
        }
    }

    fn table_started(&mut self, table: &str) {
        self.table.clear();
        self.table.push_str(table);
        self.rows = 0;
        self.emit(true, format!("carregando {table}"));
    }

    fn row(&mut self) {
        self.rows += 1;
        if self.enabled && self.last_report.elapsed() >= self.interval {
            self.emit(false, format!("carregando {}: {} linhas", self.table, self.rows));
        }
    }

    fn table_finished(&mut self) {
        self.emit(true, format!("{}: {} linhas", self.table, self.rows));
    }

    fn complete(&mut self, tables: usize, rows: u64) {
        self.emit(true, format!("materialização concluída: {tables} tabelas, {rows} linhas"));
    }

    fn emit(&mut self, force: bool, detail: String) {
        if !self.enabled || (!force && self.last_report.elapsed() < self.interval) {
            return;
        }
        let elapsed = self.started.elapsed().as_secs_f64();
        eprintln!("[ETL +{elapsed:.0}s] {detail}");
        self.last_report = Instant::now();
    }
}

fn main() {
    let raw_args: Vec<OsString> = std::env::args_os().collect();
    let result = match raw_args.get(1).and_then(|value| value.to_str()) {
        Some("aggregate") => {
            let mut aggregate_args = raw_args;
            aggregate_args.remove(1);
            aggregate::run(aggregate::AggregateArgs::parse_from(aggregate_args))
        }
        Some("serve") => {
            let mut serve_args = raw_args;
            serve_args.remove(1);
            serve::run(serve::ServeArgs::parse_from(serve_args))
        }
        _ => run().map_err(|error| error.to_string()),
    };
    if let Err(error) = result {
        eprintln!("musicbrainz-etl: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), EtlError> {
    let args = Args::parse();
    if args.snapshot_version.trim().is_empty() {
        return Err(EtlError::InvalidArgument("--snapshot-version is required".into()));
    }
    ensure_empty_output(&args.output)?;
    fs::create_dir_all(args.output.join("tables"))?;

    let mut progress = Progress::new(!args.no_progress, args.progress_interval);
    let mut outputs = BTreeMap::new();
    for spec in TABLE_SPECS {
        outputs.insert(spec.name.to_string(), spec);
    }

    let mut table_manifests = if args.dump.is_dir() {
        materialize_directory(&args.dump, &args.output, &mut progress)?
    } else {
        materialize_archive(&args.dump, &args.output, &outputs, &mut progress)?
    };

    let mut missing = Vec::new();
    for spec in TABLE_SPECS.iter().filter(|spec| spec.required) {
        if !table_manifests.contains_key(spec.name) {
            missing.push(spec.name);
        }
    }
    if !missing.is_empty() {
        return Err(EtlError::MissingTable(missing.join(", ")));
    }

    let mut manifest_hasher = Sha256::new();
    let mut row_count = 0;
    let mut projected_bytes = 0;
    for (name, table) in &table_manifests {
        manifest_hasher.update(name.as_bytes());
        manifest_hasher.update(table.sha256.as_bytes());
        row_count += table.rows;
        projected_bytes += table.bytes;
    }
    let generated_at = now_unix();
    let manifest = Manifest {
        schema_version: SCHEMA_VERSION,
        snapshot_version: args.snapshot_version,
        generated_at,
        source: "MusicBrainz",
        source_url: args.source_url,
        license: args.license,
        attribution: args.attribution,
        table_count: table_manifests.len(),
        row_count,
        projected_bytes,
        manifest_hash: hex_digest(manifest_hasher.finalize()),
        tables: std::mem::take(&mut table_manifests),
    };
    let manifest_bytes = serde_json::to_vec_pretty(&manifest)?;
    fs::write(args.output.join("manifest.json"), [manifest_bytes.as_slice(), b"\n"].concat())?;
    fs::write(args.output.join("LICENSE-MUSICBRAINZ.txt"), license_notice(&manifest))?;
    progress.complete(manifest.table_count, manifest.row_count);
    println!("{}", serde_json::to_string_pretty(&manifest)?);
    Ok(())
}

fn materialize_directory(
    dump: &Path,
    output: &Path,
    progress: &mut Progress,
) -> Result<BTreeMap<String, TableManifest>, EtlError> {
    let mut paths = BTreeMap::new();
    collect_files(dump, &mut paths)?;
    let mut manifests = BTreeMap::new();
    for spec in TABLE_SPECS {
        let Some(path) = paths.get(spec.name) else { continue };
        let file = File::open(path)?;
        let reader: Box<dyn Read> = if path.extension().and_then(|value| value.to_str()) == Some("bz2") {
            Box::new(BzDecoder::new(file))
        } else {
            Box::new(file)
        };
        let manifest = materialize_table(reader, spec, output, progress)?;
        manifests.insert(spec.name.to_string(), manifest);
    }
    Ok(manifests)
}

fn materialize_archive(
    dump: &Path,
    output: &Path,
    specs: &BTreeMap<String, &'static TableSpec>,
    progress: &mut Progress,
) -> Result<BTreeMap<String, TableManifest>, EtlError> {
    let file = File::open(dump)?;
    let reader: Box<dyn Read> = if dump.extension().and_then(|value| value.to_str()) == Some("bz2") {
        Box::new(BzDecoder::new(file))
    } else {
        Box::new(file)
    };
    let mut archive = Archive::new(reader);
    let mut manifests = BTreeMap::new();
    for entry in archive.entries()? {
        let mut entry = entry?;
        if !entry.header().entry_type().is_file() {
            continue;
        }
        let path = entry.path()?.to_path_buf();
        let Some(name) = path.file_name().and_then(|value| value.to_str()) else { continue };
        let normalized = normalize_table_name(name);
        let Some(spec) = specs.get(&normalized) else { continue };
        if manifests.contains_key(&normalized) {
            return Err(EtlError::InvalidArgument(format!("duplicate table in archive: {normalized}")));
        }
        let manifest = materialize_table(&mut entry, spec, output, progress)?;
        manifests.insert(normalized, manifest);
    }
    Ok(manifests)
}

fn materialize_table<R: Read>(
    reader: R,
    spec: &TableSpec,
    output: &Path,
    progress: &mut Progress,
) -> Result<TableManifest, EtlError> {
    progress.table_started(spec.name);
    let path = output.join("tables").join(format!("{}.jsonl", spec.name));
    let mut output_file = TableOutput::create(&path)?;
    let buffered = BufReader::with_capacity(1024 * 1024, reader);
    for_each_copy_row(buffered, |row| {
        let projected = spec
            .columns
            .iter()
            .map(|index| {
                row.get(*index).cloned().ok_or_else(|| {
                    EtlError::InvalidCopy(format!(
                        "table {} row has {} columns; required column {} is absent",
                        spec.name,
                        row.len(),
                        index,
                    ))
                })
            })
            .collect::<Result<Vec<_>, _>>()?;
        output_file.write_projected_row(&projected)?;
        progress.row();
        Ok(())
    })?;
    let rows = output_file.rows;
    let bytes = output_file.bytes;
    let digest = output_file.digest.clone().finalize();
    output_file.writer.flush()?;
    drop(output_file);
    progress.table_finished();
    Ok(TableManifest {
        columns: spec.columns.to_vec(),
        required: spec.required,
        rows,
        bytes,
        sha256: hex_digest(digest),
    })
}

fn for_each_copy_row<R: BufRead, F>(mut reader: R, mut callback: F) -> Result<(), EtlError>
where
    F: FnMut(Vec<Option<String>>) -> Result<(), EtlError>,
{
    let mut line = String::new();
    loop {
        line.clear();
        let read = reader.read_line(&mut line)?;
        if read == 0 {
            break;
        }
        let trimmed = line.trim_end_matches(['\n', '\r']);
        if trimmed.is_empty() {
            continue;
        }
        callback(parse_copy_row(trimmed)?)?;
    }
    Ok(())
}

fn parse_copy_row(line: &str) -> Result<Vec<Option<String>>, EtlError> {
    line.split('\t').map(decode_copy_field).collect()
}

fn decode_copy_field(field: &str) -> Result<Option<String>, EtlError> {
    if field == r"\N" {
        return Ok(None);
    }
    let mut output = String::with_capacity(field.len());
    let chars: Vec<char> = field.chars().collect();
    let mut index = 0;
    while index < chars.len() {
        if chars[index] != '\\' {
            output.push(chars[index]);
            index += 1;
            continue;
        }
        index += 1;
        if index >= chars.len() {
            return Err(EtlError::InvalidCopy("trailing escape".into()));
        }
        match chars[index] {
            't' => output.push('\t'),
            'n' => output.push('\n'),
            'r' => output.push('\r'),
            '\\' => output.push('\\'),
            'b' => output.push('\u{0008}'),
            'f' => output.push('\u{000c}'),
            'v' => output.push('\u{000b}'),
            '0'..='7' => {
                let mut value = chars[index].to_digit(8).unwrap_or(0);
                let mut consumed = 1;
                while consumed < 3 && index + consumed < chars.len() {
                    let Some(digit) = chars[index + consumed].to_digit(8) else { break };
                    value = value * 8 + digit;
                    consumed += 1;
                }
                let character = char::from_u32(value).ok_or_else(|| {
                    EtlError::InvalidCopy(format!("invalid octal escape in {field:?}"))
                })?;
                output.push(character);
                index += consumed - 1;
            }
            other => output.push(other),
        }
        index += 1;
    }
    Ok(Some(output))
}

fn collect_files(root: &Path, files: &mut BTreeMap<String, PathBuf>) -> Result<(), EtlError> {
    for entry in fs::read_dir(root)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            collect_files(&path, files)?;
            continue;
        }
        let Some(name) = path.file_name().and_then(|value| value.to_str()) else { continue };
        let normalized = normalize_table_name(name);
        if TABLE_SPECS.iter().any(|spec| spec.name == normalized) {
            files.entry(normalized).or_insert(path);
        }
    }
    Ok(())
}

fn normalize_table_name(name: &str) -> String {
    let mut normalized = name.rsplit('/').next().unwrap_or(name).to_string();
    for suffix in [".bz2", ".gz", ".tsv", ".txt"] {
        if normalized.ends_with(suffix) {
            normalized.truncate(normalized.len() - suffix.len());
            break;
        }
    }
    normalized
}

fn ensure_empty_output(path: &Path) -> Result<(), EtlError> {
    if path.exists() {
        if !path.is_dir() {
            return Err(EtlError::InvalidArgument(format!("output is not a directory: {}", path.display())));
        }
        if fs::read_dir(path)?.next().is_some() {
            return Err(EtlError::InvalidArgument(format!("output directory is not empty: {}", path.display())));
        }
    } else {
        fs::create_dir_all(path)?;
    }
    Ok(())
}

fn license_notice(manifest: &Manifest) -> String {
    format!(
        "This staging artifact is derived from MusicBrainz data.\nAttribution: {}\nSource: {}\nLicense: {}\nSnapshot: {}\nSchema: {}\n",
        manifest.attribution,
        manifest.source_url,
        manifest.license,
        manifest.snapshot_version,
        manifest.schema_version,
    )
}

fn hex_digest<D: AsRef<[u8]>>(digest: D) -> String {
    digest.as_ref().iter().map(|byte| format!("{byte:02x}")).collect()
}

fn now_unix() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    format!("unix:{seconds}")
}

fn positive_float(value: &str) -> Result<f64, String> {
    let parsed = value.parse::<f64>().map_err(|_| "must be a number".to_string())?;
    if parsed <= 0.0 || !parsed.is_finite() {
        return Err("must be greater than zero".into());
    }
    Ok(parsed)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn copy_parser_decodes_nulls_and_escapes() {
        let row = parse_copy_row("1\tline\\ntext\t\\N\t\\\\slash").unwrap();
        assert_eq!(row[0].as_deref(), Some("1"));
        assert_eq!(row[1].as_deref(), Some("line\ntext"));
        assert_eq!(row[2], None);
        assert_eq!(row[3].as_deref(), Some("\\slash"));
    }

    #[test]
    fn medium_projection_uses_release_column_one() {
        let spec = TABLE_SPECS.iter().find(|spec| spec.name == "medium").unwrap();
        let row: Vec<Option<String>> = vec![
            Some("42".into()),
            Some("9001".into()),
            Some("2".into()),
        ];
        let projected = spec.columns.iter().map(|index| row[*index].clone()).collect::<Vec<_>>();
        assert_eq!(
            projected,
            vec![Some("42".to_string()), Some("9001".to_string())]
        );
    }

    #[test]
    fn table_names_drop_compression_and_text_suffixes() {
        assert_eq!(normalize_table_name("mbdump/recording.bz2"), "recording");
        assert_eq!(normalize_table_name("track.tsv"), "track");
    }
}
