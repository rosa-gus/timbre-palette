//! Relational aggregation stage for the MusicBrainz staging projection.
//!
//! The materializer keeps the dump readable and cheap to validate. This
//! module performs the joins needed by the next artifact: direct recording
//! evidence, release-scoped context, track aliases, and the first version of
//! the artist vocabulary statistics. It deliberately writes local JSONL
//! files; publishing those files to R2 is a separate concern.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use clap::Parser;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const STAGING_SCHEMA_VERSION: &str = "musicbrainz-etl-staging-v1";
const AGGREGATE_SCHEMA_VERSION: &str = "musicbrainz-etl-aggregate-v1";
const DEFAULT_SOURCE_URL: &str = "https://musicbrainz.org/doc/MusicBrainz_Database/Download";
const DEFAULT_ATTRIBUTION: &str = "MusicBrainz; derived instrumental-credit index.";
const DEFAULT_LICENSE: &str = "CC0";

const CONTEXT_RELATIONS: &[&str] = &["vocal", "vocals", "programming", "samples", "sampled"];

#[derive(Debug, Parser)]
#[command(
    name = "aggregate",
    bin_name = "musicbrainz-etl aggregate",
    about = "Aggregate a MusicBrainz staging snapshot"
)]
pub(crate) struct AggregateArgs {
    /// Staging directory produced by the materializer.
    pub staging: PathBuf,

    /// Empty directory where aggregate JSONL files will be written.
    pub output: PathBuf,

    /// Snapshot version that must match the staging manifest.
    #[arg(long)]
    pub snapshot_version: String,

    /// Minimum distinct recordings for an artist/instrument vocabulary entry.
    #[arg(long, default_value_t = 3)]
    pub min_recordings: u32,

    /// Seconds between progress messages written to stderr.
    #[arg(long, default_value_t = 5.0, value_parser = positive_float)]
    pub progress_interval: f64,

    #[arg(long, help = "Disable progress output on stderr")]
    pub no_progress: bool,
}

#[derive(Debug, Deserialize)]
struct StagingManifest {
    schema_version: String,
    snapshot_version: String,
    source_url: Option<String>,
    license: Option<String>,
    attribution: Option<String>,
    manifest_hash: String,
}

#[derive(Debug, Clone)]
struct Artist {
    mbid: String,
    name: String,
}

#[derive(Debug, Clone)]
struct Recording {
    mbid: String,
    title: String,
}

#[derive(Debug, Clone)]
struct Release {
    mbid: String,
    title: String,
}

#[derive(Debug, Clone)]
struct Instrument {
    key: u32,
    mbid: String,
    name: String,
}

#[derive(Debug, Clone)]
struct AttributeType {
    name: String,
    instrument: Option<Instrument>,
}

#[derive(Debug, Clone)]
struct Relation {
    relation_type: String,
    attributes: Vec<String>,
    instruments: Vec<Instrument>,
    original_credit: Option<String>,
}

#[derive(Debug, Serialize)]
struct DirectEvidence {
    recording_mbid: String,
    recording_title: String,
    artist_mbid: Option<String>,
    performer: Option<String>,
    instrument_mbid: Option<String>,
    instrument_name: String,
    attributes: Vec<String>,
    original_credit: Option<String>,
    scope: &'static str,
    relation_type: String,
    production_method: String,
    source_url: String,
    snapshot_version: String,
}

#[derive(Debug, Serialize)]
struct ReleaseContext {
    recording_mbid: String,
    recording_title: String,
    release_mbid: String,
    release_title: String,
    artist_mbid: Option<String>,
    performer: Option<String>,
    instrument_mbid: Option<String>,
    instrument_name: String,
    attributes: Vec<String>,
    original_credit: Option<String>,
    scope: &'static str,
    relation_type: String,
    production_method: String,
    source_url: String,
    snapshot_version: String,
}

#[derive(Debug, Serialize)]
struct TrackAlias {
    track_mbid: String,
    recording_mbid: String,
    source_url: String,
    snapshot_version: String,
}

#[derive(Debug, Serialize)]
struct VocabularyEntry {
    artist_mbid: Option<String>,
    artist_name: Option<String>,
    instrument_mbid: String,
    instrument_name: String,
    distinct_recordings: u32,
    documented_recordings: u32,
    prevalence: f64,
    qualifying: bool,
    snapshot_version: String,
}

#[derive(Debug, Serialize)]
struct FileManifest {
    rows: u64,
    bytes: u64,
    sha256: String,
}

#[derive(Debug, Serialize)]
struct AggregateManifest {
    schema_version: &'static str,
    snapshot_version: String,
    generated_at: String,
    source: &'static str,
    source_url: String,
    license: String,
    attribution: String,
    staging_manifest_hash: String,
    min_recordings: u32,
    file_count: usize,
    row_count: u64,
    manifest_hash: String,
    files: BTreeMap<String, FileManifest>,
}

struct JsonlOutput {
    writer: BufWriter<File>,
    digest: Sha256,
    rows: u64,
    bytes: u64,
}

impl JsonlOutput {
    fn create(path: &Path) -> Result<Self, String> {
        let file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(path)
            .map_err(|error| format!("cannot create {}: {error}", path.display()))?;
        Ok(Self {
            writer: BufWriter::with_capacity(1024 * 1024, file),
            digest: Sha256::new(),
            rows: 0,
            bytes: 0,
        })
    }

    fn write<T: Serialize>(&mut self, value: &T) -> Result<(), String> {
        let mut encoded = serde_json::to_vec(value).map_err(|error| error.to_string())?;
        encoded.push(b'\n');
        self.writer.write_all(&encoded).map_err(|error| error.to_string())?;
        self.digest.update(&encoded);
        self.rows += 1;
        self.bytes += encoded.len() as u64;
        Ok(())
    }

    fn finish(mut self) -> Result<FileManifest, String> {
        self.writer.flush().map_err(|error| error.to_string())?;
        Ok(FileManifest {
            rows: self.rows,
            bytes: self.bytes,
            sha256: hex_digest(self.digest.finalize()),
        })
    }
}

struct Progress {
    enabled: bool,
    interval: Duration,
    started: Instant,
    last_report: Instant,
}

impl Progress {
    fn new(enabled: bool, interval_seconds: f64) -> Self {
        let now = Instant::now();
        Self {
            enabled,
            interval: Duration::from_secs_f64(interval_seconds),
            started: now,
            last_report: now,
        }
    }

    fn report(&mut self, detail: impl AsRef<str>, force: bool) {
        if !self.enabled || (!force && self.last_report.elapsed() < self.interval) {
            return;
        }
        eprintln!(
            "[ETL aggregate +{:.0}s] {}",
            self.started.elapsed().as_secs_f64(),
            detail.as_ref()
        );
        self.last_report = Instant::now();
    }
}

#[derive(Debug, Deserialize, Serialize)]
struct RawTrackAlias {
    track_mbid: String,
    recording_id: u32,
}

pub(crate) fn run(args: AggregateArgs) -> Result<(), String> {
    if args.snapshot_version.trim().is_empty() {
        return Err("--snapshot-version is required".into());
    }
    if args.min_recordings == 0 {
        return Err("--min-recordings must be greater than zero".into());
    }
    ensure_empty_output(&args.output)?;
    let mut progress = Progress::new(!args.no_progress, args.progress_interval);

    let staging_manifest = read_staging_manifest(&args.staging)?;
    if staging_manifest.schema_version != STAGING_SCHEMA_VERSION {
        return Err(format!(
            "unsupported staging schema: {}",
            staging_manifest.schema_version
        ));
    }
    if staging_manifest.snapshot_version != args.snapshot_version {
        return Err(format!(
            "snapshot mismatch: staging is {}, requested {}",
            staging_manifest.snapshot_version, args.snapshot_version
        ));
    }
    let tables = args.staging.join("tables");
    validate_required_tables(&tables)?;

    progress.report("carregando dimensões", true);
    let link_types = load_link_types(&tables)?;
    let links = load_links(&tables)?;
    let instruments = load_instruments(&tables)?;
    let attributes = load_attributes(&tables, instruments)?;
    let credits = load_credits(&tables)?;
    let relations = RelationCatalog { link_types, links, attributes, credits };

    progress.report("selecionando relações de gravação", true);
    let (direct_recordings, direct_artists) = collect_recording_relations(&tables, &relations)?;
    let (release_relations, release_artists) = collect_release_relations(&tables, &relations)?;
    let mut relevant_recordings = direct_recordings;
    let mut relevant_artists = direct_artists;

    let mut releases = HashMap::new();
    let mut release_to_recordings: HashMap<u32, HashSet<u32>> = HashMap::new();
    let alias_path = args.output.join(".track-aliases.ids.jsonl");
    let mut alias_output = JsonlOutput::create(&alias_path)?;
    let mut medium_to_release = HashMap::new();
    if !release_relations.is_empty() {
        releases = load_releases(&tables, &release_relations)?;
        medium_to_release = load_media(&tables, &release_relations)?;
        relevant_artists.extend(release_artists);
    }
    // Track aliases are useful for direct recording evidence as well as
    // release-scoped evidence, so scan the track projection in both cases.
    scan_tracks(
        &tables,
        &medium_to_release,
        &mut release_to_recordings,
        &mut relevant_recordings,
        &mut alias_output,
    )?;
    alias_output.finish()?;
    progress.report(
        format!(
            "relações selecionadas: {} gravações, {} artistas, {} lançamentos",
            relevant_recordings.len(),
            relevant_artists.len(),
            releases.len()
        ),
        true,
    );

    let artists = load_artists(&tables, &relevant_artists)?;
    let recordings = load_recordings(&tables, &relevant_recordings)?;

    let mut direct_output = JsonlOutput::create(&args.output.join("direct-evidence.jsonl"))?;
    let mut release_output = JsonlOutput::create(&args.output.join("release-context.jsonl"))?;
    let mut vocabulary_output = JsonlOutput::create(&args.output.join("artist-vocabulary.jsonl"))?;
    let mut aliases_output = JsonlOutput::create(&args.output.join("track-aliases.jsonl"))?;

    let mut vocabulary_observations: HashSet<(u32, u32, u32)> = HashSet::new();
    let mut documented_recordings: HashSet<(u32, u32)> = HashSet::new();
    progress.report("emitindo evidência direta", true);
    emit_direct_evidence(
        &tables,
        &relations,
        &artists,
        &recordings,
        &args.snapshot_version,
        &mut direct_output,
        &mut vocabulary_observations,
        &mut documented_recordings,
    )?;

    progress.report("emitindo contexto de lançamento", true);
    emit_release_context(
        &tables,
        &relations,
        &artists,
        &recordings,
        &releases,
        &release_to_recordings,
        &args.snapshot_version,
        &mut release_output,
    )?;

    progress.report("emitindo aliases de faixa", true);
    write_aliases(
        &alias_path,
        &recordings,
        &args.snapshot_version,
        &mut aliases_output,
    )?;
    fs::remove_file(&alias_path).map_err(|error| format!("cannot remove temporary alias file: {error}"))?;

    progress.report("emitindo vocabulário do artista", true);
    emit_vocabulary(
        &vocabulary_observations,
        &documented_recordings,
        &artists,
        &relations,
        &args.snapshot_version,
        args.min_recordings,
        &mut vocabulary_output,
    )?;

    let mut files: BTreeMap<String, FileManifest> = BTreeMap::new();
    files.insert("direct-evidence.jsonl".into(), direct_output.finish()?);
    files.insert("release-context.jsonl".into(), release_output.finish()?);
    files.insert("track-aliases.jsonl".into(), aliases_output.finish()?);
    files.insert("artist-vocabulary.jsonl".into(), vocabulary_output.finish()?);
    let mut manifest_hasher = Sha256::new();
    let mut row_count = 0;
    for (name, file) in &files {
        manifest_hasher.update(name.as_bytes());
        manifest_hasher.update(file.sha256.as_bytes());
        row_count += file.rows;
    }
    let source_url = staging_manifest
        .source_url
        .unwrap_or_else(|| DEFAULT_SOURCE_URL.into());
    let license = staging_manifest.license.unwrap_or_else(|| DEFAULT_LICENSE.into());
    let attribution = staging_manifest
        .attribution
        .unwrap_or_else(|| DEFAULT_ATTRIBUTION.into());
    let manifest = AggregateManifest {
        schema_version: AGGREGATE_SCHEMA_VERSION,
        snapshot_version: args.snapshot_version,
        generated_at: now_unix(),
        source: "MusicBrainz",
        source_url,
        license,
        attribution,
        staging_manifest_hash: staging_manifest.manifest_hash,
        min_recordings: args.min_recordings,
        file_count: files.len(),
        row_count,
        manifest_hash: hex_digest(manifest_hasher.finalize()),
        files,
    };
    let encoded = serde_json::to_vec_pretty(&manifest).map_err(|error| error.to_string())?;
    fs::write(args.output.join("manifest.json"), [encoded.as_slice(), b"\n"].concat())
        .map_err(|error| error.to_string())?;
    fs::write(args.output.join("LICENSE-MUSICBRAINZ.txt"), license_notice(&manifest))
        .map_err(|error| error.to_string())?;
    progress.report(format!("agregação concluída: {} linhas", manifest.row_count), true);
    println!(
        "{}",
        serde_json::to_string_pretty(&manifest).map_err(|error| error.to_string())?
    );
    Ok(())
}

struct RelationCatalog {
    link_types: HashMap<u32, String>,
    links: HashMap<u32, u32>,
    attributes: HashMap<u32, Vec<AttributeTypeWithId>>,
    credits: HashMap<(u32, u32), String>,
}

#[derive(Debug, Clone)]
struct AttributeTypeWithId {
    id: u32,
    value: AttributeType,
}

impl RelationCatalog {
    fn is_supported(&self, link_id: u32) -> bool {
        let Some(link_type_id) = self.links.get(&link_id) else {
            return false;
        };
        let Some(relation_type) = self.link_types.get(link_type_id) else {
            return false;
        };
        relation_type == "instrument" || CONTEXT_RELATIONS.contains(&relation_type.as_str())
    }

    fn relation(&self, link_id: u32) -> Option<Relation> {
        let link_type_id = *self.links.get(&link_id)?;
        let relation_type = self.link_types.get(&link_type_id)?.clone();
        if relation_type != "instrument" && !CONTEXT_RELATIONS.contains(&relation_type.as_str()) {
            return None;
        }
        let mut attributes = Vec::new();
        let mut instruments = Vec::new();
        let mut seen_instruments = HashSet::new();
        let mut original_credit = None;
        if let Some(values) = self.attributes.get(&link_id) {
            for value in values {
                if !attributes.iter().any(|name| name == &value.value.name) {
                    attributes.push(value.value.name.clone());
                }
                if let Some(instrument) = &value.value.instrument {
                    if seen_instruments.insert(instrument.key) {
                        instruments.push(instrument.clone());
                    }
                }
                if let Some(credit) = self.credits.get(&(link_id, value.id)) {
                    if original_credit.as_ref().is_none_or(|current| credit > current) {
                        original_credit = Some(credit.clone());
                    }
                }
            }
        }
        Some(Relation {
            relation_type,
            attributes,
            instruments,
            original_credit,
        })
    }
}

fn collect_recording_relations(
    tables: &Path,
    relations: &RelationCatalog,
) -> Result<(HashSet<u32>, HashSet<u32>), String> {
    let mut recordings = HashSet::new();
    let mut artists = HashSet::new();
    for_each_jsonl(&table_path(tables, "l_artist_recording"), |row| {
        let link = required_u32(&row, 0, "l_artist_recording")?;
        let artist = required_u32(&row, 1, "l_artist_recording")?;
        let recording = required_u32(&row, 2, "l_artist_recording")?;
        if relations.is_supported(link) {
            recordings.insert(recording);
            artists.insert(artist);
        }
        Ok(())
    })?;
    Ok((recordings, artists))
}

fn collect_release_relations(
    tables: &Path,
    relations: &RelationCatalog,
) -> Result<(HashSet<u32>, HashSet<u32>), String> {
    let path = table_path(tables, "l_artist_release");
    if !path.exists() {
        return Ok((HashSet::new(), HashSet::new()));
    }
    let mut releases = HashSet::new();
    let mut artists = HashSet::new();
    for_each_jsonl(&path, |row| {
        let link = required_u32(&row, 0, "l_artist_release")?;
        let artist = required_u32(&row, 1, "l_artist_release")?;
        let release = required_u32(&row, 2, "l_artist_release")?;
        if relations.is_supported(link) {
            releases.insert(release);
            artists.insert(artist);
        }
        Ok(())
    })?;
    Ok((releases, artists))
}

fn emit_direct_evidence(
    tables: &Path,
    relations: &RelationCatalog,
    artists: &HashMap<u32, Artist>,
    recordings: &HashMap<u32, Recording>,
    snapshot_version: &str,
    output: &mut JsonlOutput,
    vocabulary_observations: &mut HashSet<(u32, u32, u32)>,
    documented_recordings: &mut HashSet<(u32, u32)>,
) -> Result<(), String> {
    for_each_jsonl(&table_path(tables, "l_artist_recording"), |row| {
        let link_id = required_u32(&row, 0, "l_artist_recording")?;
        let artist_id = required_u32(&row, 1, "l_artist_recording")?;
        let recording_id = required_u32(&row, 2, "l_artist_recording")?;
        let Some(relation) = relations.relation(link_id) else { return Ok(()) };
        let Some(recording) = recordings.get(&recording_id) else { return Ok(()) };
        let artist = artists.get(&artist_id);
        for instrument in relation.instruments.iter() {
            vocabulary_observations.insert((artist_id, instrument.key, recording_id));
            documented_recordings.insert((artist_id, recording_id));
            output.write(&direct_row(
                recording,
                artist,
                &relation,
                Some(instrument),
                snapshot_version,
            ))?;
        }
        if relation.instruments.is_empty() && relation.relation_type != "instrument" {
            documented_recordings.insert((artist_id, recording_id));
            output.write(&direct_row(recording, artist, &relation, None, snapshot_version))?;
        }
        Ok(())
    })
}

fn emit_release_context(
    tables: &Path,
    relations: &RelationCatalog,
    artists: &HashMap<u32, Artist>,
    recordings: &HashMap<u32, Recording>,
    releases: &HashMap<u32, Release>,
    release_to_recordings: &HashMap<u32, HashSet<u32>>,
    snapshot_version: &str,
    output: &mut JsonlOutput,
) -> Result<(), String> {
    let path = table_path(tables, "l_artist_release");
    if !path.exists() {
        return Ok(());
    }
    for_each_jsonl(&path, |row| {
        let link_id = required_u32(&row, 0, "l_artist_release")?;
        let artist_id = required_u32(&row, 1, "l_artist_release")?;
        let release_id = required_u32(&row, 2, "l_artist_release")?;
        let Some(relation) = relations.relation(link_id) else { return Ok(()) };
        let Some(release) = releases.get(&release_id) else { return Ok(()) };
        let Some(recording_ids) = release_to_recordings.get(&release_id) else { return Ok(()) };
        let artist = artists.get(&artist_id);
        let mut recording_ids: Vec<u32> = recording_ids.iter().copied().collect();
        recording_ids.sort_unstable();
        for recording_id in recording_ids {
            let Some(recording) = recordings.get(&recording_id) else { continue };
            for instrument in relation.instruments.iter() {
                output.write(&release_row(
                    recording,
                    release,
                    artist,
                    &relation,
                    Some(instrument),
                    snapshot_version,
                ))?;
            }
            if relation.instruments.is_empty() && relation.relation_type != "instrument" {
                output.write(&release_row(
                    recording,
                    release,
                    artist,
                    &relation,
                    None,
                    snapshot_version,
                ))?;
            }
        }
        Ok(())
    })
}

fn direct_row(
    recording: &Recording,
    artist: Option<&Artist>,
    relation: &Relation,
    instrument: Option<&Instrument>,
    snapshot_version: &str,
) -> DirectEvidence {
    let (instrument_mbid, instrument_name) = instrument_values(relation, instrument);
    let mut attributes = relation.attributes.clone();
    if !attributes.iter().any(|attribute| attribute == &instrument_name) {
        attributes.push(instrument_name.clone());
    }
    DirectEvidence {
        recording_mbid: recording.mbid.clone(),
        recording_title: recording.title.clone(),
        artist_mbid: artist.map(|value| value.mbid.clone()),
        performer: artist.map(|value| value.name.clone()),
        instrument_mbid,
        instrument_name: instrument_name.clone(),
        attributes,
        original_credit: relation
            .original_credit
            .clone()
            .or_else(|| Some(instrument_name)),
        scope: "recording",
        relation_type: relation.relation_type.clone(),
        production_method: production_method(&relation.relation_type).into(),
        source_url: format!("https://musicbrainz.org/recording/{}", recording.mbid),
        snapshot_version: snapshot_version.into(),
    }
}

fn release_row(
    recording: &Recording,
    release: &Release,
    artist: Option<&Artist>,
    relation: &Relation,
    instrument: Option<&Instrument>,
    snapshot_version: &str,
) -> ReleaseContext {
    let (instrument_mbid, instrument_name) = instrument_values(relation, instrument);
    let mut attributes = relation.attributes.clone();
    if !attributes.iter().any(|attribute| attribute == &instrument_name) {
        attributes.push(instrument_name.clone());
    }
    ReleaseContext {
        recording_mbid: recording.mbid.clone(),
        recording_title: recording.title.clone(),
        release_mbid: release.mbid.clone(),
        release_title: release.title.clone(),
        artist_mbid: artist.map(|value| value.mbid.clone()),
        performer: artist.map(|value| value.name.clone()),
        instrument_mbid,
        instrument_name: instrument_name.clone(),
        attributes,
        original_credit: relation
            .original_credit
            .clone()
            .or_else(|| Some(instrument_name)),
        scope: "release",
        relation_type: relation.relation_type.clone(),
        production_method: production_method(&relation.relation_type).into(),
        source_url: format!("https://musicbrainz.org/release/{}", release.mbid),
        snapshot_version: snapshot_version.into(),
    }
}

fn instrument_values(relation: &Relation, instrument: Option<&Instrument>) -> (Option<String>, String) {
    if let Some(instrument) = instrument {
        return (Some(instrument.mbid.clone()), instrument.name.clone());
    }
    let name = match relation.relation_type.as_str() {
        "vocal" | "vocals" => "voice",
        other => other,
    };
    (None, name.into())
}

fn production_method(relation_type: &str) -> &'static str {
    match relation_type {
        "programming" => "programmed",
        "samples" | "sampled" => "sampled",
        _ => "performed",
    }
}

fn emit_vocabulary(
    observations: &HashSet<(u32, u32, u32)>,
    documented: &HashSet<(u32, u32)>,
    artists: &HashMap<u32, Artist>,
    relations: &RelationCatalog,
    snapshot_version: &str,
    min_recordings: u32,
    output: &mut JsonlOutput,
) -> Result<(), String> {
    let mut counts: HashMap<(u32, u32), u32> = HashMap::new();
    for (artist_id, instrument_key, _) in observations {
        *counts.entry((*artist_id, *instrument_key)).or_default() += 1;
    }
    let mut documented_counts: HashMap<u32, u32> = HashMap::new();
    for (artist_id, _) in documented {
        *documented_counts.entry(*artist_id).or_default() += 1;
    }
    let mut entries: Vec<_> = counts.into_iter().collect();
    entries.sort_unstable_by_key(|((artist, instrument), _)| (*artist, *instrument));
    for ((artist_id, instrument_key), distinct_recordings) in entries {
        let instrument = find_instrument(relations, instrument_key)
            .ok_or_else(|| format!("instrument key {instrument_key} is missing"))?;
        let total = documented_counts.get(&artist_id).copied().unwrap_or(0);
        output.write(&VocabularyEntry {
            artist_mbid: artists.get(&artist_id).map(|value| value.mbid.clone()),
            artist_name: artists.get(&artist_id).map(|value| value.name.clone()),
            instrument_mbid: instrument.mbid.clone(),
            instrument_name: instrument.name.clone(),
            distinct_recordings,
            documented_recordings: total,
            prevalence: if total == 0 {
                0.0
            } else {
                f64::from(distinct_recordings) / f64::from(total)
            },
            qualifying: distinct_recordings >= min_recordings,
            snapshot_version: snapshot_version.into(),
        })?;
    }
    Ok(())
}

fn find_instrument(relations: &RelationCatalog, key: u32) -> Option<&Instrument> {
    relations
        .attributes
        .values()
        .flat_map(|values| values.iter())
        .filter_map(|value| value.value.instrument.as_ref())
        .find(|instrument| instrument.key == key)
}

fn load_link_types(tables: &Path) -> Result<HashMap<u32, String>, String> {
    let mut values = HashMap::new();
    for_each_jsonl(&table_path(tables, "link_type"), |row| {
        values.insert(
            required_u32(&row, 0, "link_type")?,
            required_text(&row, 1, "link_type")?.to_lowercase(),
        );
        Ok(())
    })?;
    Ok(values)
}

fn load_links(tables: &Path) -> Result<HashMap<u32, u32>, String> {
    let mut values = HashMap::new();
    for_each_jsonl(&table_path(tables, "link"), |row| {
        values.insert(
            required_u32(&row, 0, "link")?,
            required_u32(&row, 1, "link")?,
        );
        Ok(())
    })?;
    Ok(values)
}

fn load_instruments(tables: &Path) -> Result<HashMap<String, (String, String)>, String> {
    let mut values = HashMap::new();
    for_each_jsonl(&table_path(tables, "instrument"), |row| {
        let gid = required_text(&row, 1, "instrument")?;
        values.insert(gid.clone(), (gid, required_text(&row, 2, "instrument")?));
        Ok(())
    })?;
    Ok(values)
}

fn load_attributes(
    tables: &Path,
    instruments: HashMap<String, (String, String)>,
) -> Result<HashMap<u32, Vec<AttributeTypeWithId>>, String> {
    let mut next_key = 1u32;
    let mut instrument_keys = HashMap::<String, u32>::new();
    let mut attribute_types = HashMap::<u32, AttributeType>::new();
    for_each_jsonl(&table_path(tables, "link_attribute_type"), |row| {
        let id = required_u32(&row, 0, "link_attribute_type")?;
        let gid = optional_text(&row, 1);
        let name = required_text(&row, 2, "link_attribute_type")?;
        let instrument = gid.and_then(|gid| {
            instruments.get(&gid).map(|(mbid, instrument_name)| {
                let key = *instrument_keys.entry(gid.clone()).or_insert_with(|| {
                    let current = next_key;
                    next_key += 1;
                    current
                });
                Instrument {
                    key,
                    mbid: mbid.clone(),
                    name: instrument_name.clone(),
                }
            })
        });
        attribute_types.insert(id, AttributeType { name, instrument });
        Ok(())
    })?;
    let mut values: HashMap<u32, Vec<AttributeTypeWithId>> = HashMap::new();
    for_each_jsonl(&table_path(tables, "link_attribute"), |row| {
        let link_id = required_u32(&row, 0, "link_attribute")?;
        let attribute_type_id = required_u32(&row, 1, "link_attribute")?;
        let Some(attribute_type) = attribute_types.get(&attribute_type_id) else { return Ok(()) };
        values.entry(link_id).or_default().push(AttributeTypeWithId {
            id: attribute_type_id,
            value: attribute_type.clone(),
        });
        Ok(())
    })?;
    Ok(values)
}

fn load_credits(tables: &Path) -> Result<HashMap<(u32, u32), String>, String> {
    let path = table_path(tables, "link_attribute_credit");
    if !path.exists() {
        return Ok(HashMap::new());
    }
    let mut values = HashMap::new();
    for_each_jsonl(&path, |row| {
        let key = (
            required_u32(&row, 0, "link_attribute_credit")?,
            required_u32(&row, 1, "link_attribute_credit")?,
        );
        let credit = optional_text(&row, 2);
        if let Some(credit) = credit {
            let replace = values.get(&key).is_none_or(|current: &String| credit > *current);
            if replace {
                values.insert(key, credit);
            }
        }
        Ok(())
    })?;
    Ok(values)
}

fn load_releases(tables: &Path, ids: &HashSet<u32>) -> Result<HashMap<u32, Release>, String> {
    let path = table_path(tables, "release");
    if !path.exists() {
        return Ok(HashMap::new());
    }
    let mut values = HashMap::new();
    for_each_jsonl(&path, |row| {
        let id = required_u32(&row, 0, "release")?;
        if ids.contains(&id) {
            values.insert(id, Release {
                mbid: required_text(&row, 1, "release")?,
                title: required_text(&row, 2, "release")?,
            });
        }
        Ok(())
    })?;
    Ok(values)
}

fn load_media(tables: &Path, release_ids: &HashSet<u32>) -> Result<HashMap<u32, u32>, String> {
    let path = table_path(tables, "medium");
    if !path.exists() {
        return Ok(HashMap::new());
    }
    let mut values = HashMap::new();
    for_each_jsonl(&path, |row| {
        let medium = required_u32(&row, 0, "medium")?;
        let release = required_u32(&row, 1, "medium")?;
        if release_ids.contains(&release) {
            values.insert(medium, release);
        }
        Ok(())
    })?;
    Ok(values)
}

fn scan_tracks(
    tables: &Path,
    medium_to_release: &HashMap<u32, u32>,
    release_to_recordings: &mut HashMap<u32, HashSet<u32>>,
    relevant_recordings: &mut HashSet<u32>,
    aliases: &mut JsonlOutput,
) -> Result<(), String> {
    for_each_jsonl(&table_path(tables, "track"), |row| {
        let track_mbid = required_text(&row, 0, "track")?;
        let recording = required_u32(&row, 1, "track")?;
        let medium = required_u32(&row, 2, "track")?;
        let release = medium_to_release.get(&medium).copied();
        let direct_recording = relevant_recordings.contains(&recording);
        if release.is_none() && !direct_recording {
            return Ok(());
        }
        if let Some(release) = release {
            release_to_recordings.entry(release).or_default().insert(recording);
            relevant_recordings.insert(recording);
        }
        aliases.write(&RawTrackAlias {
            track_mbid,
            recording_id: recording,
        })
    })
}

fn load_artists(tables: &Path, ids: &HashSet<u32>) -> Result<HashMap<u32, Artist>, String> {
    let mut values = HashMap::new();
    for_each_jsonl(&table_path(tables, "artist"), |row| {
        let id = required_u32(&row, 0, "artist")?;
        if ids.contains(&id) {
            values.insert(id, Artist {
                mbid: required_text(&row, 1, "artist")?,
                name: required_text(&row, 2, "artist")?,
            });
        }
        Ok(())
    })?;
    Ok(values)
}

fn load_recordings(tables: &Path, ids: &HashSet<u32>) -> Result<HashMap<u32, Recording>, String> {
    let mut values = HashMap::new();
    for_each_jsonl(&table_path(tables, "recording"), |row| {
        let id = required_u32(&row, 0, "recording")?;
        if ids.contains(&id) {
            values.insert(id, Recording {
                mbid: required_text(&row, 1, "recording")?,
                title: required_text(&row, 2, "recording")?,
            });
        }
        Ok(())
    })?;
    Ok(values)
}

fn write_aliases(
    raw_path: &Path,
    recordings: &HashMap<u32, Recording>,
    snapshot_version: &str,
    output: &mut JsonlOutput,
) -> Result<(), String> {
    for_each_typed_jsonl::<RawTrackAlias, _>(raw_path, |raw| {
        let track_mbid = raw.track_mbid;
        let recording_id = raw.recording_id;
        let Some(recording) = recordings.get(&recording_id) else { return Ok(()) };
        output.write(&TrackAlias {
            track_mbid: track_mbid.clone(),
            recording_mbid: recording.mbid.clone(),
            source_url: format!("https://musicbrainz.org/track/{track_mbid}"),
            snapshot_version: snapshot_version.into(),
        })
    })
}

fn read_staging_manifest(staging: &Path) -> Result<StagingManifest, String> {
    let bytes = fs::read(staging.join("manifest.json"))
        .map_err(|error| format!("cannot read staging manifest: {error}"))?;
    serde_json::from_slice(&bytes).map_err(|error| format!("invalid staging manifest: {error}"))
}

fn validate_required_tables(tables: &Path) -> Result<(), String> {
    const REQUIRED: &[&str] = &[
        "artist",
        "instrument",
        "link_type",
        "link",
        "link_attribute_type",
        "link_attribute",
        "l_artist_recording",
        "recording",
        "track",
    ];
    for table in REQUIRED {
        let path = table_path(tables, table);
        if !path.exists() {
            return Err(format!("required staging table is missing: {}", path.display()));
        }
    }
    Ok(())
}

fn for_each_jsonl<F>(path: &Path, mut callback: F) -> Result<(), String>
where
    F: FnMut(Vec<Option<String>>) -> Result<(), String>,
{
    let file = File::open(path).map_err(|error| format!("cannot read {}: {error}", path.display()))?;
    let reader = BufReader::with_capacity(1024 * 1024, file);
    for (line_number, line) in reader.lines().enumerate() {
        let line = line.map_err(|error| format!("cannot read {}: {error}", path.display()))?;
        if line.trim().is_empty() {
            continue;
        }
        let row: Vec<Option<String>> = serde_json::from_str(&line)
            .map_err(|error| format!("invalid JSON in {} line {}: {error}", path.display(), line_number + 1))?;
        callback(row)?;
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
        let row: T = serde_json::from_str(&line)
            .map_err(|error| format!("invalid JSON in {} line {}: {error}", path.display(), line_number + 1))?;
        callback(row)?;
    }
    Ok(())
}

fn table_path(tables: &Path, name: &str) -> PathBuf {
    tables.join(format!("{name}.jsonl"))
}

fn required_text(row: &[Option<String>], index: usize, table: &str) -> Result<String, String> {
    row.get(index)
        .and_then(|value| value.clone())
        .filter(|value| !value.is_empty())
        .ok_or_else(|| format!("{table} row is missing required column {index}"))
}

fn optional_text(row: &[Option<String>], index: usize) -> Option<String> {
    row.get(index).and_then(|value| value.clone()).filter(|value| !value.is_empty())
}

fn required_u32(row: &[Option<String>], index: usize, table: &str) -> Result<u32, String> {
    let value = required_text(row, index, table)?;
    value
        .parse::<u32>()
        .map_err(|error| format!("{table} column {index} is not an integer: {error}"))
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

fn license_notice(manifest: &AggregateManifest) -> String {
    format!(
        "This aggregate artifact is derived from MusicBrainz data.\nAttribution: {}\nSource: {}\nLicense: {}\nSnapshot: {}\nSchema: {}\nStaging manifest: {}\n",
        manifest.attribution,
        manifest.source_url,
        manifest.license,
        manifest.snapshot_version,
        manifest.schema_version,
        manifest.staging_manifest_hash,
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
