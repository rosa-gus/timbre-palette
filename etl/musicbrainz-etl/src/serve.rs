//! Serving snapshot builder for the aggregated MusicBrainz evidence.
//!
//! The aggregate is intentionally verbose and useful for audits. This stage
//! converts it into deterministic bzip2-compressed shards suitable for R2:
//! recording evidence is grouped by recording MBID, release evidence is kept
//! only when no direct evidence exists, aliases are grouped by track MBID,
//! and vocabulary entries are grouped by artist MBID.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs::{self, File, OpenOptions};
use std::io::{self, BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};

use bzip2::write::BzEncoder;
use bzip2::Compression;
use clap::Parser;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const AGGREGATE_SCHEMA_VERSION: &str = "musicbrainz-etl-aggregate-v1";
const SERVING_SCHEMA_VERSION: &str = "musicbrainz-instrument-credits-serving-v1";
const SERVING_OBJECT_PREFIX: &str = "musicbrainz/instrument-credits/v2";
const DEFAULT_SHARDS: usize = 256;
const DEFAULT_COMPRESSION_LEVEL: u32 = 6;
const DEFAULT_SOURCE_URL: &str = "https://musicbrainz.org/doc/MusicBrainz_Database/Download";
const DEFAULT_ATTRIBUTION: &str = "MusicBrainz; derived instrumental-credit index.";
const DEFAULT_LICENSE: &str = "CC0";

#[derive(Debug, Parser)]
#[command(
    name = "serve",
    bin_name = "musicbrainz-etl serve",
    about = "Build a compact MusicBrainz serving snapshot"
)]
pub(crate) struct ServeArgs {
    /// Aggregate directory produced by the `aggregate` subcommand.
    pub aggregate: PathBuf,

    /// Empty directory where compressed serving shards will be written.
    pub output: PathBuf,

    /// Snapshot version that must match the aggregate manifest.
    #[arg(long)]
    pub snapshot_version: String,

    /// Number of hexadecimal-prefix shards. Must be a power of sixteen.
    #[arg(long, default_value_t = DEFAULT_SHARDS, value_parser = positive_usize)]
    pub shards: usize,

    /// Bzip2 compression level for serving objects (1-9).
    #[arg(long, default_value_t = DEFAULT_COMPRESSION_LEVEL, value_parser = compression_level)]
    pub compression_level: u32,

    /// Seconds between progress messages written to stderr.
    #[arg(long, default_value_t = 5.0, value_parser = positive_float)]
    pub progress_interval: f64,

    #[arg(long, help = "Disable progress output on stderr")]
    pub no_progress: bool,
}

#[derive(Debug, Deserialize)]
struct AggregateManifest {
    schema_version: String,
    snapshot_version: String,
    source_url: Option<String>,
    license: Option<String>,
    attribution: Option<String>,
    manifest_hash: String,
}

#[derive(Debug, Deserialize)]
struct AggregateEvidence {
    recording_mbid: String,
    #[serde(default)]
    artist_mbid: Option<String>,
    #[serde(default)]
    instrument_mbid: Option<String>,
    #[serde(default)]
    instrument_name: String,
    #[serde(default)]
    attributes: Vec<String>,
    #[serde(default)]
    original_credit: Option<String>,
    #[serde(default = "default_recording_scope")]
    scope: String,
    #[serde(default = "default_instrument_relation")]
    relation_type: String,
    #[serde(default = "default_performed_method")]
    production_method: String,
    #[serde(default)]
    source_url: String,
    #[serde(default)]
    snapshot_version: String,
    #[serde(default)]
    performer: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
struct AggregateAlias {
    track_mbid: String,
    recording_mbid: String,
}

#[derive(Debug, Deserialize, Serialize)]
struct AggregateVocabulary {
    artist_mbid: Option<String>,
    #[serde(default)]
    artist_name: Option<String>,
    instrument_mbid: String,
    instrument_name: String,
    distinct_recordings: u32,
    documented_recordings: u32,
    prevalence: f64,
    qualifying: bool,
}

#[derive(Debug, Clone, Deserialize, Serialize, Eq, Hash, Ord, PartialEq, PartialOrd)]
struct ServeCredit {
    #[serde(skip_serializing_if = "Option::is_none")]
    artist_mbid: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    instrument_mbid: Option<String>,
    instrument_name: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    attributes: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    original_credit: Option<String>,
    scope: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    source_url: Option<String>,
    relation_type: String,
    production_method: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    performer: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
struct SpoolEvidence {
    recording_mbid: String,
    credit: ServeCredit,
}

#[derive(Debug, Serialize)]
struct ServingRecord {
    recording_mbid: String,
    source_url: String,
    credits: Vec<ServeCredit>,
}

#[derive(Debug, Serialize)]
struct RecordingShard {
    schema_version: &'static str,
    snapshot_version: String,
    shard: String,
    records: BTreeMap<String, ServingRecord>,
}

#[derive(Debug, Serialize)]
struct AliasShard {
    schema_version: &'static str,
    snapshot_version: String,
    shard: String,
    aliases: BTreeMap<String, String>,
}

#[derive(Debug, Serialize)]
struct ServingVocabularyEntry {
    instrument_mbid: String,
    instrument_name: String,
    distinct_recordings: u32,
    documented_recordings: u32,
    prevalence: f64,
    qualifying: bool,
}

#[derive(Debug, Serialize)]
struct ServingArtist {
    artist_mbid: String,
    artist_name: Option<String>,
    entries: Vec<ServingVocabularyEntry>,
}

#[derive(Debug, Serialize)]
struct VocabularyShard {
    schema_version: &'static str,
    snapshot_version: String,
    shard: String,
    artists: BTreeMap<String, ServingArtist>,
}

#[derive(Debug, Serialize)]
struct FileManifest {
    rows: u64,
    bytes: u64,
    sha256: String,
}

#[derive(Debug, Serialize)]
struct ServingManifest {
    schema_version: &'static str,
    snapshot_version: String,
    generated_at: String,
    source: &'static str,
    source_url: String,
    license: String,
    attribution: String,
    aggregate_manifest_hash: String,
    object_prefix: &'static str,
    shard_count: usize,
    shard_width: usize,
    compression: &'static str,
    recording_count: u64,
    credit_count: u64,
    release_fallback_recordings: u64,
    alias_count: u64,
    orphan_alias_count: u64,
    vocabulary_entries: u64,
    qualifying_vocabulary_entries: u64,
    discarded_unresolved_instrument_rows: u64,
    discarded_invalid_evidence_rows: u64,
    discarded_invalid_alias_rows: u64,
    discarded_invalid_vocabulary_rows: u64,
    file_count: usize,
    manifest_hash: String,
    files: BTreeMap<String, FileManifest>,
}

#[derive(Default)]
struct Counters {
    input_evidence_rows: u64,
    discarded_unresolved_instrument_rows: u64,
    discarded_invalid_evidence_rows: u64,
    discarded_invalid_alias_rows: u64,
    discarded_invalid_vocabulary_rows: u64,
    recording_count: u64,
    credit_count: u64,
    release_fallback_recordings: u64,
    alias_count: u64,
    orphan_alias_count: u64,
    vocabulary_entries: u64,
    qualifying_vocabulary_entries: u64,
}

struct ShardSpool {
    paths: Vec<PathBuf>,
    writers: Vec<BufWriter<File>>,
}

impl ShardSpool {
    fn create(root: &Path, shard_count: usize, width: usize) -> Result<Self, String> {
        fs::create_dir_all(root).map_err(|error| format!("cannot create {}: {error}", root.display()))?;
        let mut paths = Vec::with_capacity(shard_count);
        let mut writers = Vec::with_capacity(shard_count);
        for shard in 0..shard_count {
            let path = root.join(format!("{shard:0width$x}.jsonl"));
            let file = OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(&path)
                .map_err(|error| format!("cannot create {}: {error}", path.display()))?;
            paths.push(path);
            writers.push(BufWriter::with_capacity(64 * 1024, file));
        }
        Ok(Self { paths, writers })
    }

    fn write<T: Serialize>(&mut self, shard: usize, value: &T) -> Result<(), String> {
        let mut encoded = serde_json::to_vec(value).map_err(|error| error.to_string())?;
        encoded.push(b'\n');
        self.writers[shard]
            .write_all(&encoded)
            .map_err(|error| error.to_string())
    }

    fn finish(mut self) -> Result<Vec<PathBuf>, String> {
        for writer in &mut self.writers {
            writer.flush().map_err(|error| error.to_string())?;
        }
        Ok(self.paths)
    }
}

struct DigestWriter {
    writer: BufWriter<File>,
    digest: Sha256,
    bytes: u64,
}

impl Write for DigestWriter {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        self.writer.write_all(buffer)?;
        self.digest.update(buffer);
        self.bytes += buffer.len() as u64;
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        self.writer.flush()
    }
}

struct RecordAccumulator {
    direct: HashSet<ServeCredit>,
    release: HashSet<ServeCredit>,
}

impl Default for RecordAccumulator {
    fn default() -> Self {
        Self {
            direct: HashSet::new(),
            release: HashSet::new(),
        }
    }
}

struct Progress {
    enabled: bool,
    interval: std::time::Duration,
    started: std::time::Instant,
    last_report: std::time::Instant,
}

impl Progress {
    fn new(enabled: bool, interval_seconds: f64) -> Self {
        let now = std::time::Instant::now();
        Self {
            enabled,
            interval: std::time::Duration::from_secs_f64(interval_seconds),
            started: now,
            last_report: now,
        }
    }

    fn report(&mut self, detail: impl AsRef<str>, force: bool) {
        if !self.enabled || (!force && self.last_report.elapsed() < self.interval) {
            return;
        }
        eprintln!(
            "[ETL serve +{:.0}s] {}",
            self.started.elapsed().as_secs_f64(),
            detail.as_ref()
        );
        self.last_report = std::time::Instant::now();
    }
}

pub(crate) fn run(args: ServeArgs) -> Result<(), String> {
    if args.snapshot_version.trim().is_empty() {
        return Err("--snapshot-version is required".into());
    }
    let shard_width = shard_width(args.shards)?;
    ensure_empty_output(&args.output)?;
    let input = read_aggregate_manifest(&args.aggregate)?;
    if input.schema_version != AGGREGATE_SCHEMA_VERSION {
        return Err(format!("unsupported aggregate schema: {}", input.schema_version));
    }
    if input.snapshot_version != args.snapshot_version {
        return Err(format!(
            "snapshot mismatch: aggregate is {}, requested {}",
            input.snapshot_version, args.snapshot_version
        ));
    }
    validate_aggregate_files(&args.aggregate)?;
    fs::create_dir_all(args.output.join("recordings"))
        .map_err(|error| format!("cannot create recording output: {error}"))?;
    fs::create_dir_all(args.output.join("tracks"))
        .map_err(|error| format!("cannot create track output: {error}"))?;
    fs::create_dir_all(args.output.join("artists"))
        .map_err(|error| format!("cannot create artist output: {error}"))?;
    let temporary = args.output.join(".serving-tmp");
    fs::create_dir_all(&temporary).map_err(|error| error.to_string())?;
    let mut progress = Progress::new(!args.no_progress, args.progress_interval);
    let mut counters = Counters::default();
    let mut files = BTreeMap::new();

    progress.report("particionando evidência", true);
    let mut evidence_spool = ShardSpool::create(
        &temporary.join("recordings"),
        args.shards,
        shard_width,
    )?;
    scan_evidence_file(
        &args.aggregate.join("direct-evidence.jsonl"),
        &args.snapshot_version,
        args.shards,
        shard_width,
        &mut evidence_spool,
        &mut counters,
    )?;
    scan_evidence_file(
        &args.aggregate.join("release-context.jsonl"),
        &args.snapshot_version,
        args.shards,
        shard_width,
        &mut evidence_spool,
        &mut counters,
    )?;
    let evidence_paths = evidence_spool.finish()?;

    progress.report("gerando shards de gravação", true);
    let servable_recordings = emit_recording_shards(
        &evidence_paths,
        &args.output.join("recordings"),
        &args.snapshot_version,
        args.shards,
        shard_width,
        args.compression_level,
        &mut files,
        &mut counters,
    )?;

    progress.report("particionando aliases", true);
    let mut alias_spool = ShardSpool::create(&temporary.join("tracks"), args.shards, shard_width)?;
    scan_alias_file(
        &args.aggregate.join("track-aliases.jsonl"),
        args.shards,
        shard_width,
        &mut alias_spool,
        &mut counters,
    )?;
    let alias_paths = alias_spool.finish()?;
    emit_alias_shards(
        &alias_paths,
        &args.output.join("tracks"),
        &args.snapshot_version,
        args.shards,
        shard_width,
        args.compression_level,
        &servable_recordings,
        &mut files,
        &mut counters,
    )?;

    progress.report("particionando vocabulário", true);
    let mut vocabulary_spool = ShardSpool::create(&temporary.join("artists"), args.shards, shard_width)?;
    scan_vocabulary_file(
        &args.aggregate.join("artist-vocabulary.jsonl"),
        args.shards,
        shard_width,
        &mut vocabulary_spool,
        &mut counters,
    )?;
    let vocabulary_paths = vocabulary_spool.finish()?;
    emit_vocabulary_shards(
        &vocabulary_paths,
        &args.output.join("artists"),
        &args.snapshot_version,
        args.shards,
        shard_width,
        args.compression_level,
        &mut files,
    )?;
    fs::remove_dir_all(&temporary).map_err(|error| format!("cannot remove temporary serving data: {error}"))?;

    let source_url = input.source_url.unwrap_or_else(|| DEFAULT_SOURCE_URL.into());
    let license = input.license.unwrap_or_else(|| DEFAULT_LICENSE.into());
    let attribution = input.attribution.unwrap_or_else(|| DEFAULT_ATTRIBUTION.into());
    let mut manifest_hasher = Sha256::new();
    for (name, file) in &files {
        manifest_hasher.update(name.as_bytes());
        manifest_hasher.update(file.sha256.as_bytes());
    }
    let manifest = ServingManifest {
        schema_version: SERVING_SCHEMA_VERSION,
        snapshot_version: args.snapshot_version,
        generated_at: now_unix(),
        source: "MusicBrainz",
        source_url,
        license,
        attribution,
        aggregate_manifest_hash: input.manifest_hash,
        object_prefix: SERVING_OBJECT_PREFIX,
        shard_count: args.shards,
        shard_width,
        compression: "bzip2",
        recording_count: counters.recording_count,
        credit_count: counters.credit_count,
        release_fallback_recordings: counters.release_fallback_recordings,
        alias_count: counters.alias_count,
        orphan_alias_count: counters.orphan_alias_count,
        vocabulary_entries: counters.vocabulary_entries,
        qualifying_vocabulary_entries: counters.qualifying_vocabulary_entries,
        discarded_unresolved_instrument_rows: counters.discarded_unresolved_instrument_rows,
        discarded_invalid_evidence_rows: counters.discarded_invalid_evidence_rows,
        discarded_invalid_alias_rows: counters.discarded_invalid_alias_rows,
        discarded_invalid_vocabulary_rows: counters.discarded_invalid_vocabulary_rows,
        file_count: files.len(),
        manifest_hash: hex_digest(manifest_hasher.finalize()),
        files,
    };
    let encoded = serde_json::to_vec_pretty(&manifest).map_err(|error| error.to_string())?;
    fs::write(args.output.join("manifest.json"), [encoded.as_slice(), b"\n"].concat())
        .map_err(|error| error.to_string())?;
    fs::write(args.output.join("LICENSE-MUSICBRAINZ.txt"), license_notice(&manifest))
        .map_err(|error| error.to_string())?;
    progress.report(format!("serving concluído: {} gravações, {} shards", manifest.recording_count, manifest.file_count), true);
    println!(
        "{}",
        serde_json::to_string_pretty(&manifest).map_err(|error| error.to_string())?
    );
    Ok(())
}

fn scan_evidence_file(
    path: &Path,
    snapshot_version: &str,
    shard_count: usize,
    shard_width: usize,
    spool: &mut ShardSpool,
    counters: &mut Counters,
) -> Result<(), String> {
    for_each_typed_jsonl::<AggregateEvidence, _>(path, |row| {
        counters.input_evidence_rows += 1;
        if !row.snapshot_version.is_empty() && row.snapshot_version != snapshot_version {
            return Err(format!(
                "snapshot mismatch in {}: found {}",
                path.display(),
                row.snapshot_version
            ));
        }
        let Some(recording_mbid) = canonical_mbid(&row.recording_mbid) else {
            counters.discarded_invalid_evidence_rows += 1;
            return Ok(());
        };
        let relation_type = if row.relation_type.trim().is_empty() {
            "instrument".to_string()
        } else {
            row.relation_type.trim().to_ascii_lowercase()
        };
        let instrument_mbid = row.instrument_mbid.as_deref().and_then(canonical_mbid);
        if relation_type == "instrument" && instrument_mbid.is_none() {
            counters.discarded_unresolved_instrument_rows += 1;
            return Ok(());
        }
        let instrument_name = row.instrument_name.trim().to_string();
        if instrument_name.is_empty() {
            counters.discarded_invalid_evidence_rows += 1;
            return Ok(());
        }
        let artist_mbid = row.artist_mbid.as_deref().and_then(canonical_mbid);
        let mut attributes = Vec::new();
        for attribute in row.attributes {
            let attribute = attribute.trim();
            if !attribute.is_empty() && !attributes.iter().any(|value| value == attribute) {
                attributes.push(attribute.to_string());
            }
        }
        if !attributes.iter().any(|value| value == &instrument_name) {
            attributes.push(instrument_name.clone());
        }
        let scope = match row.scope.trim() {
            "release" => "release",
            "recording" | "" => "recording",
            _ => {
                counters.discarded_invalid_evidence_rows += 1;
                return Ok(());
            }
        };
        let credit = ServeCredit {
            artist_mbid,
            instrument_mbid,
            instrument_name,
            attributes,
            original_credit: row.original_credit.filter(|value| !value.trim().is_empty()),
            scope: scope.into(),
            source_url: if row.source_url.trim().is_empty() {
                None
            } else {
                Some(row.source_url)
            },
            relation_type,
            production_method: if row.production_method.trim().is_empty() {
                "performed".into()
            } else {
                row.production_method.trim().to_string()
            },
            performer: row.performer.filter(|value| !value.trim().is_empty()),
        };
        spool.write(
            shard_index(&recording_mbid, shard_count, shard_width),
            &SpoolEvidence {
                recording_mbid,
                credit,
            },
        )
    })
}

fn emit_recording_shards(
    paths: &[PathBuf],
    output: &Path,
    snapshot_version: &str,
    shard_count: usize,
    shard_width: usize,
    compression_level: u32,
    files: &mut BTreeMap<String, FileManifest>,
    counters: &mut Counters,
) -> Result<HashSet<String>, String> {
    let mut servable = HashSet::new();
    for (shard, path) in paths.iter().enumerate() {
        let mut records: HashMap<String, RecordAccumulator> = HashMap::new();
        for_each_typed_jsonl::<SpoolEvidence, _>(path, |row| {
            let entry = records.entry(row.recording_mbid).or_default();
            if row.credit.scope == "release" {
                entry.release.insert(row.credit);
            } else {
                entry.direct.insert(row.credit);
            }
            Ok(())
        })?;
        if records.is_empty() {
            fs::remove_file(path).map_err(|error| error.to_string())?;
            continue;
        }
        let mut output_records = BTreeMap::new();
        for (recording_mbid, accumulator) in records {
            let use_release = accumulator.direct.is_empty();
            let mut credits: Vec<ServeCredit> = if use_release {
                accumulator.release.into_iter().collect()
            } else {
                accumulator.direct.into_iter().collect()
            };
            if credits.is_empty() {
                continue;
            }
            credits.sort();
            if use_release {
                counters.release_fallback_recordings += 1;
            }
            counters.recording_count += 1;
            counters.credit_count += credits.len() as u64;
            servable.insert(recording_mbid.clone());
            output_records.insert(
                recording_mbid.clone(),
                ServingRecord {
                    recording_mbid: recording_mbid.clone(),
                    source_url: format!("https://musicbrainz.org/recording/{recording_mbid}"),
                    credits,
                },
            );
        }
        if output_records.is_empty() {
            fs::remove_file(path).map_err(|error| error.to_string())?;
            continue;
        }
        let shard_name = shard_name(shard, shard_width);
        let relative = format!("recordings/{shard_name}.json.bz2");
        let output_path = output.join(format!("{shard_name}.json.bz2"));
        let row_count = output_records.len() as u64;
        let file_manifest = write_compressed_json(
            &output_path,
            &RecordingShard {
                schema_version: SERVING_SCHEMA_VERSION,
                snapshot_version: snapshot_version.into(),
                shard: shard_name.clone(),
                records: output_records,
            },
            compression_level,
            row_count,
        )?;
        files.insert(relative, file_manifest);
        fs::remove_file(path).map_err(|error| error.to_string())?;
    }
    if paths.len() != shard_count {
        return Err("recording spool shard count mismatch".into());
    }
    Ok(servable)
}

fn scan_alias_file(
    path: &Path,
    shard_count: usize,
    shard_width: usize,
    spool: &mut ShardSpool,
    counters: &mut Counters,
) -> Result<(), String> {
    for_each_typed_jsonl::<AggregateAlias, _>(path, |row| {
        let Some(track_mbid) = canonical_mbid(&row.track_mbid) else {
            counters.discarded_invalid_alias_rows += 1;
            return Ok(());
        };
        let Some(recording_mbid) = canonical_mbid(&row.recording_mbid) else {
            counters.discarded_invalid_alias_rows += 1;
            return Ok(());
        };
        spool.write(
            shard_index(&track_mbid, shard_count, shard_width),
            &AggregateAlias {
                track_mbid,
                recording_mbid,
            },
        )
    })
}

fn emit_alias_shards(
    paths: &[PathBuf],
    output: &Path,
    snapshot_version: &str,
    shard_count: usize,
    shard_width: usize,
    compression_level: u32,
    servable: &HashSet<String>,
    files: &mut BTreeMap<String, FileManifest>,
    counters: &mut Counters,
) -> Result<(), String> {
    for (shard, path) in paths.iter().enumerate() {
        let mut aliases = BTreeMap::new();
        for_each_typed_jsonl::<AggregateAlias, _>(path, |row| {
            if !servable.contains(&row.recording_mbid) {
                counters.orphan_alias_count += 1;
                return Ok(());
            }
            if let Some(previous) = aliases.insert(row.track_mbid.clone(), row.recording_mbid.clone()) {
                if previous != row.recording_mbid {
                    return Err(format!("track alias maps to multiple recordings: {}", row.track_mbid));
                }
            }
            Ok(())
        })?;
        if aliases.is_empty() {
            fs::remove_file(path).map_err(|error| error.to_string())?;
            continue;
        }
        counters.alias_count += aliases.len() as u64;
        let shard_name = shard_name(shard, shard_width);
        let relative = format!("tracks/{shard_name}.json.bz2");
        let output_path = output.join(format!("{shard_name}.json.bz2"));
        let row_count = aliases.len() as u64;
        let file_manifest = write_compressed_json(
            &output_path,
            &AliasShard {
                schema_version: SERVING_SCHEMA_VERSION,
                snapshot_version: snapshot_version.into(),
                shard: shard_name.clone(),
                aliases,
            },
            compression_level,
            row_count,
        )?;
        files.insert(relative, file_manifest);
        fs::remove_file(path).map_err(|error| error.to_string())?;
    }
    if paths.len() != shard_count {
        return Err("alias spool shard count mismatch".into());
    }
    Ok(())
}

fn scan_vocabulary_file(
    path: &Path,
    shard_count: usize,
    shard_width: usize,
    spool: &mut ShardSpool,
    counters: &mut Counters,
) -> Result<(), String> {
    for_each_typed_jsonl::<AggregateVocabulary, _>(path, |row| {
        let Some(artist_mbid) = row.artist_mbid.as_deref().and_then(canonical_mbid) else {
            counters.discarded_invalid_vocabulary_rows += 1;
            return Ok(());
        };
        let Some(instrument_mbid) = canonical_mbid(&row.instrument_mbid) else {
            counters.discarded_invalid_vocabulary_rows += 1;
            return Ok(());
        };
        counters.vocabulary_entries += 1;
        if row.qualifying {
            counters.qualifying_vocabulary_entries += 1;
        }
        spool.write(
            shard_index(&artist_mbid, shard_count, shard_width),
            &AggregateVocabulary {
                artist_mbid: Some(artist_mbid),
                artist_name: row.artist_name,
                instrument_mbid,
                instrument_name: row.instrument_name,
                distinct_recordings: row.distinct_recordings,
                documented_recordings: row.documented_recordings,
                prevalence: row.prevalence,
                qualifying: row.qualifying,
            },
        )
    })
}

fn emit_vocabulary_shards(
    paths: &[PathBuf],
    output: &Path,
    snapshot_version: &str,
    shard_count: usize,
    shard_width: usize,
    compression_level: u32,
    files: &mut BTreeMap<String, FileManifest>,
) -> Result<(), String> {
    for (shard, path) in paths.iter().enumerate() {
        let mut artists: HashMap<String, (Option<String>, BTreeMap<String, ServingVocabularyEntry>)> = HashMap::new();
        for_each_typed_jsonl::<AggregateVocabulary, _>(path, |row| {
            let Some(artist_mbid) = row.artist_mbid else { return Ok(()) };
            let entry = artists
                .entry(artist_mbid)
                .or_insert_with(|| (row.artist_name.clone(), BTreeMap::new()));
            entry.1.insert(
                row.instrument_mbid,
                ServingVocabularyEntry {
                    instrument_mbid: String::new(),
                    instrument_name: row.instrument_name,
                    distinct_recordings: row.distinct_recordings,
                    documented_recordings: row.documented_recordings,
                    prevalence: row.prevalence,
                    qualifying: row.qualifying,
                },
            );
            Ok(())
        })?;
        if artists.is_empty() {
            fs::remove_file(path).map_err(|error| error.to_string())?;
            continue;
        }
        let mut output_artists = BTreeMap::new();
        for (artist_mbid, (artist_name, entries)) in artists {
            let mut values = Vec::with_capacity(entries.len());
            for (instrument_mbid, mut entry) in entries {
                entry.instrument_mbid = instrument_mbid;
                values.push(entry);
            }
            values.sort_by(|left, right| left.instrument_mbid.cmp(&right.instrument_mbid));
            output_artists.insert(
                artist_mbid.clone(),
                ServingArtist {
                    artist_mbid,
                    artist_name,
                    entries: values,
                },
            );
        }
        let shard_name = shard_name(shard, shard_width);
        let relative = format!("artists/{shard_name}.json.bz2");
        let output_path = output.join(format!("{shard_name}.json.bz2"));
        let row_count = output_artists.len() as u64;
        let file_manifest = write_compressed_json(
            &output_path,
            &VocabularyShard {
                schema_version: SERVING_SCHEMA_VERSION,
                snapshot_version: snapshot_version.into(),
                shard: shard_name.clone(),
                artists: output_artists,
            },
            compression_level,
            row_count,
        )?;
        files.insert(relative, file_manifest);
        fs::remove_file(path).map_err(|error| error.to_string())?;
    }
    if paths.len() != shard_count {
        return Err("vocabulary spool shard count mismatch".into());
    }
    Ok(())
}

fn write_compressed_json<T: Serialize>(
    path: &Path,
    value: &T,
    compression_level: u32,
    rows: u64,
) -> Result<FileManifest, String> {
    let file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(|error| format!("cannot create {}: {error}", path.display()))?;
    let sink = DigestWriter {
        writer: BufWriter::with_capacity(1024 * 1024, file),
        digest: Sha256::new(),
        bytes: 0,
    };
    let mut encoder = BzEncoder::new(sink, Compression::new(compression_level));
    serde_json::to_writer(&mut encoder, value).map_err(|error| error.to_string())?;
    let mut sink = encoder.finish().map_err(|error| error.to_string())?;
    sink.flush().map_err(|error| error.to_string())?;
    Ok(FileManifest {
        rows,
        bytes: sink.bytes,
        sha256: hex_digest(sink.digest.finalize()),
    })
}

fn read_aggregate_manifest(path: &Path) -> Result<AggregateManifest, String> {
    let bytes = fs::read(path.join("manifest.json"))
        .map_err(|error| format!("cannot read aggregate manifest: {error}"))?;
    serde_json::from_slice(&bytes).map_err(|error| format!("invalid aggregate manifest: {error}"))
}

fn validate_aggregate_files(aggregate: &Path) -> Result<(), String> {
    for name in [
        "direct-evidence.jsonl",
        "release-context.jsonl",
        "track-aliases.jsonl",
        "artist-vocabulary.jsonl",
    ] {
        let path = aggregate.join(name);
        if !path.is_file() {
            return Err(format!("required aggregate file is missing: {}", path.display()));
        }
    }
    Ok(())
}

fn for_each_typed_jsonl<T, F>(path: &Path, mut callback: F) -> Result<(), String>
where
    T: DeserializeOwned,
    F: FnMut(T) -> Result<(), String>,
{
    let file = File::open(path).map_err(|error| format!("cannot read {}: {error}", path.display()))?;
    let reader = BufReader::with_capacity(1024 * 1024, file);
    for (line_number, line) in reader.lines().enumerate() {
        let line = line.map_err(|error| format!("cannot read {}: {error}", path.display()))?;
        if line.trim().is_empty() {
            continue;
        }
        let row: T = serde_json::from_str(&line).map_err(|error| {
            format!("invalid JSON in {} line {}: {error}", path.display(), line_number + 1)
        })?;
        callback(row)?;
    }
    Ok(())
}

fn ensure_empty_output(path: &Path) -> Result<(), String> {
    if path.exists() {
        if !path.is_dir() {
            return Err(format!("output is not a directory: {}", path.display()));
        }
        if fs::read_dir(path)
            .map_err(|error| error.to_string())?
            .next()
            .is_some()
        {
            return Err(format!("output directory is not empty: {}", path.display()));
        }
    } else {
        fs::create_dir_all(path).map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn canonical_mbid(value: &str) -> Option<String> {
    let value = value.trim().to_ascii_lowercase();
    if value.len() != 36
        || ![8, 13, 18, 23]
            .iter()
            .all(|index| value.as_bytes().get(*index) == Some(&b'-'))
        || !value
            .bytes()
            .enumerate()
            .filter(|(index, _)| ![8, 13, 18, 23].contains(index))
            .all(|(_, byte)| byte.is_ascii_hexdigit())
    {
        return None;
    }
    Some(value)
}

fn shard_index(mbid: &str, shard_count: usize, width: usize) -> usize {
    usize::from_str_radix(&mbid[..width], 16).unwrap_or(0) % shard_count
}

fn shard_width(shard_count: usize) -> Result<usize, String> {
    if shard_count == 0 {
        return Err("--shards must be greater than zero".into());
    }
    let mut value = shard_count;
    let mut width = 0;
    while value > 1 && value % 16 == 0 {
        value /= 16;
        width += 1;
    }
    if value != 1 || width == 0 || width > 8 {
        return Err("--shards must be a power of sixteen between 16 and 4,294,967,296".into());
    }
    Ok(width)
}

fn shard_name(shard: usize, width: usize) -> String {
    format!("{shard:0width$x}")
}

fn license_notice(manifest: &ServingManifest) -> String {
    format!(
        "This serving artifact is derived from MusicBrainz data.\nAttribution: {}\nSource: {}\nLicense: {}\nSnapshot: {}\nSchema: {}\nAggregate manifest: {}\n",
        manifest.attribution,
        manifest.source_url,
        manifest.license,
        manifest.snapshot_version,
        manifest.schema_version,
        manifest.aggregate_manifest_hash,
    )
}

fn hex_digest<D: AsRef<[u8]>>(digest: D) -> String {
    digest.as_ref().iter().map(|byte| format!("{byte:02x}")).collect()
}

fn now_unix() -> String {
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    format!("unix:{seconds}")
}

fn default_recording_scope() -> String { "recording".into() }
fn default_instrument_relation() -> String { "instrument".into() }
fn default_performed_method() -> String { "performed".into() }

fn positive_usize(value: &str) -> Result<usize, String> {
    value.parse::<usize>().map_err(|_| "must be a positive integer".into())
}

fn compression_level(value: &str) -> Result<u32, String> {
    let parsed = value.parse::<u32>().map_err(|_| "must be an integer from 1 to 9".to_string())?;
    if !(1..=9).contains(&parsed) {
        return Err("must be an integer from 1 to 9".into());
    }
    Ok(parsed)
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
    use bzip2::read::BzDecoder;
    use std::io::Read;

    const RECORDING: &str = "11111111-1111-4111-8111-111111111111";
    const FALLBACK_RECORDING: &str = "22222222-2222-4222-8222-222222222222";
    const INSTRUMENT: &str = "33333333-3333-4333-8333-333333333333";
    const TRACK: &str = "55555555-5555-4555-8555-555555555555";

    fn write_jsonl<T: Serialize>(path: &Path, rows: &[T]) {
        let content = rows
            .iter()
            .map(|row| serde_json::to_string(row).unwrap())
            .collect::<Vec<_>>()
            .join("\n");
        fs::write(path, format!("{content}\n")).unwrap();
    }

    #[test]
    fn serving_filters_unresolved_instruments_and_prefers_direct_evidence() {
        let root = std::env::temp_dir().join(format!("musicbrainz-serving-test-{}", std::process::id()));
        let aggregate = root.join("aggregate");
        let output = root.join("serving");
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&aggregate).unwrap();
        fs::write(
            aggregate.join("manifest.json"),
            serde_json::json!({
                "schema_version": AGGREGATE_SCHEMA_VERSION,
                "snapshot_version": "snapshot-1",
                "source_url": DEFAULT_SOURCE_URL,
                "license": DEFAULT_LICENSE,
                "attribution": DEFAULT_ATTRIBUTION,
                "manifest_hash": "aggregate-hash"
            })
            .to_string(),
        )
        .unwrap();
        write_jsonl(
            &aggregate.join("direct-evidence.jsonl"),
            &[
                serde_json::json!({
                    "recording_mbid": RECORDING,
                    "artist_mbid": RECORDING,
                    "instrument_mbid": INSTRUMENT,
                    "instrument_name": "piano",
                    "attributes": ["piano"],
                    "scope": "recording",
                    "relation_type": "instrument",
                    "production_method": "performed",
                    "source_url": "https://musicbrainz.org/recording/11111111-1111-4111-8111-111111111111",
                    "snapshot_version": "snapshot-1"
                }),
                serde_json::json!({
                    "recording_mbid": RECORDING,
                    "instrument_mbid": null,
                    "instrument_name": "piano",
                    "scope": "recording",
                    "relation_type": "instrument",
                    "snapshot_version": "snapshot-1"
                }),
            ],
        );
        write_jsonl(
            &aggregate.join("release-context.jsonl"),
            &[serde_json::json!({
                "recording_mbid": FALLBACK_RECORDING,
                "instrument_mbid": INSTRUMENT,
                "instrument_name": "piano",
                "scope": "release",
                "relation_type": "instrument",
                "source_url": "https://musicbrainz.org/release/44444444-4444-4444-8444-444444444444",
                "snapshot_version": "snapshot-1"
            })],
        );
        write_jsonl(
            &aggregate.join("track-aliases.jsonl"),
            &[
                serde_json::json!({"track_mbid": TRACK, "recording_mbid": RECORDING}),
                serde_json::json!({"track_mbid": "66666666-6666-4666-8666-666666666666", "recording_mbid": "77777777-7777-4777-8777-777777777777"}),
            ],
        );
        write_jsonl(
            &aggregate.join("artist-vocabulary.jsonl"),
            &[serde_json::json!({
                "artist_mbid": RECORDING,
                "artist_name": "Test artist",
                "instrument_mbid": INSTRUMENT,
                "instrument_name": "piano",
                "distinct_recordings": 3,
                "documented_recordings": 3,
                "prevalence": 1.0,
                "qualifying": true,
                "snapshot_version": "snapshot-1"
            })],
        );

        run(ServeArgs {
            aggregate,
            output: output.clone(),
            snapshot_version: "snapshot-1".into(),
            shards: 16,
            compression_level: 1,
            progress_interval: 1.0,
            no_progress: true,
        })
        .unwrap();

        let manifest: serde_json::Value =
            serde_json::from_slice(&fs::read(output.join("manifest.json")).unwrap()).unwrap();
        assert_eq!(manifest["recording_count"], 2);
        assert_eq!(manifest["credit_count"], 2);
        assert_eq!(manifest["release_fallback_recordings"], 1);
        assert_eq!(manifest["discarded_unresolved_instrument_rows"], 1);
        assert_eq!(manifest["alias_count"], 1);
        assert_eq!(manifest["orphan_alias_count"], 1);

        let shard = shard_name(shard_index(RECORDING, 16, 1), 1);
        let mut decoded = String::new();
        BzDecoder::new(File::open(output.join(format!("recordings/{shard}.json.bz2"))).unwrap())
            .read_to_string(&mut decoded)
            .unwrap();
        assert!(decoded.contains(RECORDING));
        assert!(!decoded.contains("\"instrument_mbid\":null"));
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn compression_level_matches_bzip2_supported_range() {
        assert_eq!(compression_level("1"), Ok(1));
        assert_eq!(compression_level("9"), Ok(9));
        assert!(compression_level("0").is_err());
        assert!(compression_level("10").is_err());
    }
}
