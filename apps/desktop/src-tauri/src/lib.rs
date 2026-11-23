use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Mutex};
use tauri::{AppHandle, Emitter, State};
use thiserror::Error;
use uuid::Uuid;

const CONTRACT_VERSION: &str = "v1";
const DEFAULT_DEMUCS_MODEL: &str = "htdemucs";
const GUITAR_DEMUCS_MODEL: &str = "htdemucs_6s";
const DEFAULT_NOTATION_MODE: &str = "readable";
const DEFAULT_QUANTIZATION_RESOLUTION: &str = "auto";
const DEFAULT_CHORD_OUTPUT: &str = "symbols";
const DEFAULT_CONDITION_STEMS: [&str; 3] = ["bass", "vocals", "guitar"];
const STEM_NAMES: [&str; 5] = ["drums", "bass", "guitar", "vocals", "other"];
const YOUTUBE_INPUT_PREFIX: &str = "youtube_";
const PIPELINE_MEDIA_EXTENSIONS: [&str; 11] = [
    "wav", "mp3", "m4a", "flac", "ogg", "opus", "aac", "webm", "mp4", "mov", "mkv",
];
const MAX_USER_ERROR_CHARS: usize = 460;

#[derive(Clone)]
pub struct SharedState {
    inner: Arc<Mutex<RuntimeState>>,
}

impl Default for SharedState {
    fn default() -> Self {
        let settings = try_load_settings_from_disk()
            .map(normalize_settings)
            .unwrap_or_else(SettingsDto::default);
        let _ = fs::create_dir_all(&settings.data_root);
        let _ = save_settings_to_disk(&settings);
        let state = RuntimeState {
            jobs: HashMap::new(),
            settings,
        };
        Self {
            inner: Arc::new(Mutex::new(state)),
        }
    }
}

#[derive(Default)]
struct RuntimeState {
    jobs: HashMap<String, JobDto>,
    settings: SettingsDto,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProjectDto {
    pub id: String,
    pub name: String,
    pub root_path: String,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ArtifactDto {
    pub id: String,
    pub project_id: String,
    pub kind: String,
    pub path: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct JobLogEntryDto {
    pub timestamp: String,
    pub stage: String,
    pub level: String,
    pub line: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct JobDto {
    pub id: String,
    pub project_id: String,
    pub state: String,
    pub stage: String,
    pub progress: f32,
    pub message: Option<String>,
    pub started_at: String,
    pub finished_at: Option<String>,
    pub cancel_requested: bool,
    pub logs: Vec<JobLogEntryDto>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct RunConfigDto {
    pub use_placeholders: Option<bool>,
    pub contract_version: Option<String>,
    pub allow_partial_success: Option<bool>,
    pub transcribe_guitar: Option<bool>,
    pub transcribe_other: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ToolPathsDto {
    pub audio_cli: Option<String>,
    pub demucs: Option<String>,
    pub omnizart: Option<String>,
    pub basic_pitch: Option<String>,
    pub musescore: Option<String>,
    pub yt_dlp: Option<String>,
}

impl Default for ToolPathsDto {
    fn default() -> Self {
        Self {
            audio_cli: Some(detect_default_audio_cli_path()),
            demucs: Some(detect_default_demucs_path()),
            omnizart: Some(detect_default_omnizart_path()),
            basic_pitch: Some(detect_default_basic_pitch_path()),
            musescore: Some(detect_default_musescore_path()),
            yt_dlp: Some(detect_default_ytdlp_path()),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SettingsDto {
    pub contract_version: String,
    pub data_root: String,
    pub use_placeholders: bool,
    pub tool_paths: ToolPathsDto,
}

impl Default for SettingsDto {
    fn default() -> Self {
        Self {
            contract_version: CONTRACT_VERSION.to_string(),
            data_root: default_data_root().to_string_lossy().to_string(),
            use_placeholders: true,
            tool_paths: ToolPathsDto::default(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SettingsUpdateDto {
    pub data_root: Option<String>,
    pub use_placeholders: Option<bool>,
    pub tool_paths: Option<ToolPathsDto>,
}

fn non_empty_or_none(value: Option<String>) -> Option<String> {
    value.and_then(|entry| {
        let trimmed = entry.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        }
    })
}

fn normalize_tool_path_with_default(
    current: Option<String>,
    default_value: &Option<String>,
    fallback_command: &str,
) -> Option<String> {
    let normalized_current = non_empty_or_none(current);
    match (normalized_current, default_value.clone()) {
        (Some(current_value), Some(default_path))
            if current_value.eq_ignore_ascii_case(fallback_command)
                && !default_path.eq_ignore_ascii_case(fallback_command) =>
        {
            Some(default_path)
        }
        (Some(current_value), _) => Some(current_value),
        (None, Some(default_path)) => Some(default_path),
        (None, None) => None,
    }
}

fn merge_tool_paths_with_defaults(current: ToolPathsDto, defaults: &ToolPathsDto) -> ToolPathsDto {
    ToolPathsDto {
        audio_cli: normalize_tool_path_with_default(
            current.audio_cli,
            &defaults.audio_cli,
            "superscore-audio-cli",
        ),
        demucs: normalize_tool_path_with_default(current.demucs, &defaults.demucs, "demucs"),
        omnizart: normalize_tool_path_with_default(
            current.omnizart,
            &defaults.omnizart,
            "omnizart",
        ),
        basic_pitch: normalize_tool_path_with_default(
            current.basic_pitch,
            &defaults.basic_pitch,
            "basic-pitch",
        ),
        musescore: normalize_tool_path_with_default(
            current.musescore,
            &defaults.musescore,
            "musescore",
        ),
        yt_dlp: normalize_tool_path_with_default(current.yt_dlp, &defaults.yt_dlp, "yt-dlp"),
    }
}

fn normalize_settings(mut settings: SettingsDto) -> SettingsDto {
    let defaults = SettingsDto::default();
    if settings.contract_version.trim().is_empty() {
        settings.contract_version = defaults.contract_version.clone();
    }
    if settings.data_root.trim().is_empty() {
        settings.data_root = defaults.data_root.clone();
    }
    settings.tool_paths = merge_tool_paths_with_defaults(settings.tool_paths, &defaults.tool_paths);
    settings
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ProjectMeta {
    contract_version: String,
    project_id: String,
    project_name: String,
    created_at: String,
    updated_at: String,
    jobs: Vec<JobMeta>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct JobMeta {
    id: String,
    state: String,
    started_at: String,
    finished_at: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CommandError {
    pub message: String,
}

type CommandResult<T> = Result<T, CommandError>;
type AppResult<T> = Result<T, AppError>;

#[derive(Debug, Error)]
enum AppError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("invalid input: {0}")]
    InvalidInput(String),
    #[error("not found: {0}")]
    NotFound(String),
    #[error("conflict: {0}")]
    Conflict(String),
    #[error("job canceled")]
    Canceled,
    #[error("unsupported: {0}")]
    Unsupported(String),
}

impl From<AppError> for CommandError {
    fn from(value: AppError) -> Self {
        Self {
            message: value.to_string(),
        }
    }
}

impl From<std::io::Error> for CommandError {
    fn from(value: std::io::Error) -> Self {
        AppError::Io(value).into()
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct JobProgressEvent {
    job_id: String,
    stage: String,
    percent: f32,
    message: String,
    timestamp: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct JobLogEvent {
    job_id: String,
    stage: String,
    level: String,
    line: String,
    timestamp: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct JobStateEvent {
    job_id: String,
    state: String,
    stage: String,
    timestamp: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ToolContractArtifact {
    kind: String,
    path: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct ToolStageArtifact {
    kind: String,
    path: PathBuf,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ToolContractResponse {
    status: String,
    tool_version: String,
    #[serde(default)]
    artifacts: Vec<ToolContractArtifact>,
    #[serde(default)]
    warnings: Vec<String>,
    #[serde(default)]
    failed_artifacts: Vec<ToolContractArtifact>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ToolContractErrorBody {
    message: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ToolContractErrorResponse {
    status: String,
    error: Option<ToolContractErrorBody>,
}

#[derive(Debug, Clone)]
struct ToolStageResult {
    artifacts: Vec<ToolStageArtifact>,
    paths: Vec<PathBuf>,
    warnings: Vec<String>,
}

fn stage_artifact_paths(artifacts: &[ToolStageArtifact], kind: &str) -> Vec<PathBuf> {
    artifacts
        .iter()
        .filter(|artifact| artifact.kind == kind)
        .map(|artifact| artifact.path.clone())
        .collect()
}

fn exportable_midi_paths(artifacts: &[ToolStageArtifact]) -> Vec<PathBuf> {
    stage_artifact_paths(artifacts, "midi")
}

fn primary_stage_paths(subcommand: &str, artifacts: &[ToolStageArtifact]) -> Vec<PathBuf> {
    match subcommand {
        "separate" => stage_artifact_paths(artifacts, "stem"),
        "transcribe" => exportable_midi_paths(artifacts),
        "export-musicxml" => stage_artifact_paths(artifacts, "musicxml"),
        _ => artifacts
            .iter()
            .map(|artifact| artifact.path.clone())
            .collect(),
    }
}

fn to_stage_result(
    subcommand: &str,
    artifacts: Vec<ToolStageArtifact>,
    warnings: Vec<String>,
) -> ToolStageResult {
    let paths = primary_stage_paths(subcommand, &artifacts);
    ToolStageResult {
        artifacts,
        paths,
        warnings,
    }
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ToolPathOverrides {
    demucs: Option<String>,
    omnizart: Option<String>,
    basic_pitch: Option<String>,
    musescore: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SeparateOptions {
    real_execution: bool,
    model: String,
    tool_paths: ToolPathOverrides,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct TranscribeOptions {
    real_execution: bool,
    allow_partial_success: bool,
    transcribe_guitar: bool,
    transcribe_other: bool,
    notation_mode: String,
    quantization_resolution: String,
    allow_tuplets: bool,
    chord_output: String,
    condition_stems: Vec<String>,
    meter_override: Option<String>,
    tool_paths: ToolPathOverrides,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ExportMusicXmlOptions {
    real_execution: bool,
    allow_partial_success: bool,
    tool_paths: ToolPathOverrides,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SeparateRequest {
    contract_version: String,
    project_path: String,
    input_path: String,
    output_path: String,
    options: SeparateOptions,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct TranscribeRequest {
    contract_version: String,
    project_path: String,
    input_path: String,
    stem_paths: Vec<String>,
    output_path: String,
    options: TranscribeOptions,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ExportMusicXmlRequest {
    contract_version: String,
    project_path: String,
    midi_paths: Vec<String>,
    output_path: String,
    options: ExportMusicXmlOptions,
}

fn select_demucs_model(transcribe_guitar: bool) -> &'static str {
    if transcribe_guitar {
        GUITAR_DEMUCS_MODEL
    } else {
        DEFAULT_DEMUCS_MODEL
    }
}

trait ToolRunner {
    fn separate(&self, request: &SeparateRequest) -> AppResult<ToolStageResult>;
    fn transcribe(&self, request: &TranscribeRequest) -> AppResult<ToolStageResult>;
    fn export_musicxml(&self, request: &ExportMusicXmlRequest) -> AppResult<ToolStageResult>;
}

struct PlaceholderRunner;

impl ToolRunner for PlaceholderRunner {
    fn separate(&self, request: &SeparateRequest) -> AppResult<ToolStageResult> {
        let mut artifacts = Vec::new();
        let output_dir = Path::new(&request.output_path);
        fs::create_dir_all(output_dir)?;
        for stem in STEM_NAMES {
            let target = output_dir.join(format!("{stem}.wav"));
            fs::write(&target, format!("placeholder wav for {stem}\n"))?;
            artifacts.push(ToolStageArtifact {
                kind: "stem".to_string(),
                path: target,
            });
        }
        Ok(to_stage_result("separate", artifacts, Vec::new()))
    }

    fn transcribe(&self, request: &TranscribeRequest) -> AppResult<ToolStageResult> {
        let output_dir = Path::new(&request.output_path);
        fs::create_dir_all(output_dir)?;
        let mut artifacts = Vec::new();
        for stem_path in &request.stem_paths {
            let stem = Path::new(stem_path)
                .file_stem()
                .and_then(|value| value.to_str())
                .ok_or_else(|| AppError::InvalidInput(format!("bad stem path: {stem_path}")))?;
            let target = output_dir.join(format!("{stem}.mid"));
            fs::write(&target, format!("placeholder midi for {stem}\n"))?;
            artifacts.push(ToolStageArtifact {
                kind: "midi".to_string(),
                path: target,
            });
        }
        Ok(to_stage_result("transcribe", artifacts, Vec::new()))
    }

    fn export_musicxml(&self, request: &ExportMusicXmlRequest) -> AppResult<ToolStageResult> {
        let output_dir = Path::new(&request.output_path);
        fs::create_dir_all(output_dir)?;
        let mut artifacts = Vec::new();
        for midi_path in &request.midi_paths {
            let stem = Path::new(midi_path)
                .file_stem()
                .and_then(|value| value.to_str())
                .ok_or_else(|| AppError::InvalidInput(format!("bad midi path: {midi_path}")))?;
            let target = output_dir.join(format!("{stem}.musicxml"));
            fs::write(&target, format!("placeholder musicxml for {stem}\n"))?;
            artifacts.push(ToolStageArtifact {
                kind: "musicxml".to_string(),
                path: target,
            });
        }
        Ok(to_stage_result("export-musicxml", artifacts, Vec::new()))
    }
}

#[derive(Clone, Debug)]
struct JobDiagnostics {
    root: PathBuf,
}

impl JobDiagnostics {
    fn new(project_root: &Path, job_id: &str) -> AppResult<Self> {
        let root = project_root.join("runs").join(job_id);
        fs::create_dir_all(&root)?;
        Ok(Self { root })
    }

    fn ensure_stage_dir(&self, stage: &str) -> AppResult<PathBuf> {
        let dir = self.root.join(stage);
        fs::create_dir_all(&dir)?;
        Ok(dir)
    }

    fn write_stage_request<T: Serialize>(&self, stage: &str, payload: &T) -> AppResult<PathBuf> {
        let path = self.ensure_stage_dir(stage)?.join("request.json");
        fs::write(&path, serde_json::to_vec_pretty(payload)?)?;
        Ok(path)
    }

    fn write_stage_command_capture(
        &self,
        stage: &str,
        command: &str,
        args: &[String],
        exit_code: Option<i32>,
        stdout: &[u8],
        stderr: &[u8],
    ) -> AppResult<()> {
        let dir = self.ensure_stage_dir(stage)?;
        fs::write(dir.join("stdout.log"), stdout)?;
        fs::write(dir.join("stderr.log"), stderr)?;
        fs::write(
            dir.join("command.json"),
            serde_json::to_vec_pretty(&serde_json::json!({
                "command": command,
                "args": args,
                "exitCode": exit_code,
            }))?,
        )?;
        Ok(())
    }

    fn write_preflight_probe_capture(
        &self,
        name: &str,
        command: &str,
        args: &[&str],
        output: &std::process::Output,
    ) -> AppResult<()> {
        let owned_args = args.iter().map(|arg| arg.to_string()).collect::<Vec<_>>();
        let dir = self.ensure_stage_dir("preflight")?;
        fs::write(dir.join(format!("{name}.stdout.log")), &output.stdout)?;
        fs::write(dir.join(format!("{name}.stderr.log")), &output.stderr)?;
        fs::write(
            dir.join(format!("{name}.command.json")),
            serde_json::to_vec_pretty(&serde_json::json!({
                "command": command,
                "args": owned_args,
                "exitCode": output.status.code(),
            }))?,
        )?;
        Ok(())
    }

    fn write_preflight_probe_error(
        &self,
        name: &str,
        command: &str,
        args: &[&str],
        error: &str,
    ) -> AppResult<()> {
        let dir = self.ensure_stage_dir("preflight")?;
        let owned_args = args.iter().map(|arg| arg.to_string()).collect::<Vec<_>>();
        fs::write(dir.join(format!("{name}.error.txt")), error.as_bytes())?;
        fs::write(
            dir.join(format!("{name}.command.json")),
            serde_json::to_vec_pretty(&serde_json::json!({
                "command": command,
                "args": owned_args,
                "spawnError": error,
            }))?,
        )?;
        Ok(())
    }

    fn write_summary<T: Serialize>(&self, summary: &T) -> AppResult<()> {
        fs::write(
            self.root.join("summary.json"),
            serde_json::to_vec_pretty(summary)?,
        )?;
        Ok(())
    }
}

struct CliRunner {
    audio_cli: String,
    diagnostics: Option<JobDiagnostics>,
}

impl CliRunner {
    fn run_subcommand<T: Serialize>(
        &self,
        subcommand: &str,
        request: &T,
    ) -> AppResult<ToolStageResult> {
        if self.audio_cli.trim().is_empty() {
            return Err(AppError::Unsupported(
                "audio_cli executable path is empty".to_string(),
            ));
        }
        let (request_file, should_cleanup_request_file) = match &self.diagnostics {
            Some(diagnostics) => (diagnostics.write_stage_request(subcommand, request)?, false),
            None => {
                let request_file = std::env::temp_dir()
                    .join(format!("superscore-{subcommand}-{}.json", Uuid::new_v4()));
                fs::write(&request_file, serde_json::to_vec_pretty(request)?)?;
                (request_file, true)
            }
        };
        let command_args = vec![
            subcommand.to_string(),
            "--request-file".to_string(),
            request_file.to_string_lossy().to_string(),
        ];
        let output = match Command::new(&self.audio_cli)
            .arg(subcommand)
            .arg("--request-file")
            .arg(&request_file)
            .output()
        {
            Ok(output) => {
                if let Some(diagnostics) = &self.diagnostics {
                    diagnostics.write_stage_command_capture(
                        subcommand,
                        &self.audio_cli,
                        &command_args,
                        output.status.code(),
                        &output.stdout,
                        &output.stderr,
                    )?;
                }
                output
            }
            Err(error) => {
                if let Some(diagnostics) = &self.diagnostics {
                    diagnostics.write_stage_command_capture(
                        subcommand,
                        &self.audio_cli,
                        &command_args,
                        None,
                        b"",
                        error.to_string().as_bytes(),
                    )?;
                }
                return Err(AppError::Unsupported(format!(
                    "unable to execute audio_cli `{}` for {subcommand}: {error}",
                    self.audio_cli
                )));
            }
        };
        if should_cleanup_request_file {
            let _ = fs::remove_file(&request_file);
        }
        if !output.status.success() {
            let raw_stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
            return Err(AppError::Unsupported(format!(
                "tool process failed for {subcommand}: {}",
                summarize_tool_failure_stderr(&raw_stderr)
            )));
        }
        let response: ToolContractResponse = serde_json::from_slice(&output.stdout)?;
        if response.status != "ok" {
            return Err(AppError::Unsupported(format!(
                "tool returned non-ok status for {subcommand}: {}",
                response.status
            )));
        }
        let mut warnings = response.warnings;
        if !response.failed_artifacts.is_empty() {
            let failed_paths = response
                .failed_artifacts
                .iter()
                .map(|artifact| artifact.path.clone())
                .collect::<Vec<_>>()
                .join(", ");
            warnings.push(format!("failed artifacts: {failed_paths}"));
        }
        let artifacts = response
            .artifacts
            .into_iter()
            .map(|artifact| ToolStageArtifact {
                kind: artifact.kind,
                path: PathBuf::from(artifact.path),
            })
            .collect();
        Ok(to_stage_result(subcommand, artifacts, warnings))
    }
}

fn contains_numpy_abi_mismatch(text: &str) -> bool {
    let lower = text.to_lowercase();
    lower.contains("compiled using numpy 1.x")
        || lower.contains("numpy is not available")
        || lower.contains("failed to initialize numpy")
        || lower.contains("_array_api not found")
}

fn first_non_empty_line(text: &str) -> Option<String> {
    text.lines()
        .map(str::trim)
        .find(|line| !line.is_empty())
        .map(|line| line.to_string())
}

fn last_non_empty_line(text: &str) -> Option<String> {
    text.lines()
        .rev()
        .map(str::trim)
        .find(|line| !line.is_empty())
        .map(|line| line.to_string())
}

fn compact_error_message(text: &str) -> String {
    let cleaned = text.trim();
    if cleaned.chars().count() <= MAX_USER_ERROR_CHARS {
        return cleaned.to_string();
    }
    let shortened: String = cleaned.chars().take(MAX_USER_ERROR_CHARS).collect();
    format!("{shortened} ...")
}

fn summarize_tool_failure_stderr(stderr: &str) -> String {
    let extracted = serde_json::from_str::<ToolContractErrorResponse>(stderr)
        .ok()
        .and_then(|response| {
            if response.status.eq_ignore_ascii_case("error") {
                response.error.map(|item| item.message)
            } else {
                None
            }
        })
        .unwrap_or_else(|| stderr.to_string());
    if contains_numpy_abi_mismatch(&extracted) {
        return "NumPy/Torch compatibility mismatch in Demucs runtime. Rebuild the Demucs environment with `numpy<2` (same env as torch/torchaudio/demucs).".to_string();
    }
    first_non_empty_line(&extracted)
        .map(|line| compact_error_message(&line))
        .unwrap_or_else(|| "unknown tool error".to_string())
}

impl ToolRunner for CliRunner {
    fn separate(&self, request: &SeparateRequest) -> AppResult<ToolStageResult> {
        self.run_subcommand("separate", request)
    }

    fn transcribe(&self, request: &TranscribeRequest) -> AppResult<ToolStageResult> {
        self.run_subcommand("transcribe", request)
    }

    fn export_musicxml(&self, request: &ExportMusicXmlRequest) -> AppResult<ToolStageResult> {
        self.run_subcommand("export-musicxml", request)
    }
}

fn default_data_root() -> PathBuf {
    dirs::data_dir()
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
        .join("SuperScore")
        .join("data_root")
}

fn settings_store_path() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
        .join("SuperScore")
        .join("settings.json")
}

fn try_load_settings_from_disk() -> Option<SettingsDto> {
    let path = settings_store_path();
    let bytes = fs::read(path).ok()?;
    serde_json::from_slice(&bytes).ok()
}

fn save_settings_to_disk(settings: &SettingsDto) -> AppResult<()> {
    let path = settings_store_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(path, serde_json::to_vec_pretty(settings)?)?;
    Ok(())
}

fn path_exists_file(path: &Path) -> bool {
    path.exists() && path.is_file()
}

fn current_dir_candidates() -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.clone());
        let mut cursor = cwd;
        for _ in 0..6 {
            if let Some(parent) = cursor.parent() {
                candidates.push(parent.to_path_buf());
                cursor = parent.to_path_buf();
            } else {
                break;
            }
        }
    }
    candidates
}

fn join_parts(root: &Path, parts: &[&str]) -> PathBuf {
    let mut value = root.to_path_buf();
    for part in parts {
        value = value.join(part);
    }
    value
}

fn find_repo_relative_executable(parts: &[&str]) -> Option<PathBuf> {
    current_dir_candidates()
        .into_iter()
        .map(|root| join_parts(&root, parts))
        .find(|path| path_exists_file(path))
}

fn find_executable_on_path(name: &str) -> Option<PathBuf> {
    let direct = PathBuf::from(name);
    if (direct.is_absolute() || name.contains('/') || name.contains('\\'))
        && path_exists_file(&direct)
    {
        return Some(direct);
    }
    let path_var = std::env::var_os("PATH")?;
    let mut names = vec![name.to_string()];
    #[cfg(windows)]
    if Path::new(name).extension().is_none() {
        names.push(format!("{name}.exe"));
    }
    std::env::split_paths(&path_var).find_map(|folder| {
        names
            .iter()
            .map(|candidate| folder.join(candidate))
            .find(|candidate| path_exists_file(candidate))
    })
}

fn choose_tool_path(
    repo_candidates: &[&[&str]],
    path_candidates: &[&str],
    fallback: &str,
) -> String {
    for parts in repo_candidates {
        if let Some(path) = find_repo_relative_executable(parts) {
            return path.to_string_lossy().to_string();
        }
    }
    for name in path_candidates {
        if let Some(path) = find_executable_on_path(name) {
            return path.to_string_lossy().to_string();
        }
    }
    fallback.to_string()
}

fn detect_default_audio_cli_path() -> String {
    choose_tool_path(
        &[
            &[
                "apps",
                "audio-cli",
                ".venv",
                "Scripts",
                "superscore-audio-cli.exe",
            ],
            &["apps", "audio-cli", ".venv", "bin", "superscore-audio-cli"],
        ],
        &["superscore-audio-cli"],
        "superscore-audio-cli",
    )
}

fn detect_default_demucs_path() -> String {
    choose_tool_path(
        &[
            &["apps", "audio-cli", ".venv", "Scripts", "demucs.exe"],
            &["apps", "audio-cli", ".venv", "bin", "demucs"],
        ],
        &["demucs"],
        "demucs",
    )
}

fn detect_default_basic_pitch_path() -> String {
    choose_tool_path(
        &[
            &[".venv-amt-main", "Scripts", "basic-pitch.exe"],
            &[".venv-amt-main", "bin", "basic-pitch"],
        ],
        &["basic-pitch", "basic_pitch"],
        "basic-pitch",
    )
}

fn detect_default_omnizart_path() -> String {
    choose_tool_path(
        &[
            &[".venv-amt-omnizart", "Scripts", "omnizart.exe"],
            &[".venv-amt-omnizart", "bin", "omnizart"],
        ],
        &["omnizart"],
        "omnizart",
    )
}

fn detect_default_musescore_path() -> String {
    let windows_musescore = PathBuf::from(r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe");
    if path_exists_file(&windows_musescore) {
        return windows_musescore.to_string_lossy().to_string();
    }
    choose_tool_path(&[], &["musescore", "MuseScore4"], "musescore")
}

fn detect_default_ytdlp_path() -> String {
    choose_tool_path(&[], &["yt-dlp"], "yt-dlp")
}

fn now_iso() -> String {
    Utc::now().to_rfc3339()
}

fn sanitize_project_name(name: &str) -> AppResult<String> {
    let trimmed = name.trim();
    if trimmed.is_empty() {
        return Err(AppError::InvalidInput(
            "project name cannot be empty".to_string(),
        ));
    }
    let sanitized: String = trimmed
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '_' || ch == '-' {
                ch
            } else if ch.is_whitespace() {
                '_'
            } else {
                '_'
            }
        })
        .collect();
    if sanitized.chars().all(|ch| ch == '_') {
        return Err(AppError::InvalidInput(
            "project name has no usable characters".to_string(),
        ));
    }
    Ok(sanitized)
}

fn ensure_project_layout(project_root: &Path) -> AppResult<()> {
    fs::create_dir_all(project_root.join("input"))?;
    fs::create_dir_all(project_root.join("stems"))?;
    fs::create_dir_all(project_root.join("analysis"))?;
    fs::create_dir_all(project_root.join("midi").join("raw"))?;
    fs::create_dir_all(project_root.join("midi").join("clean"))?;
    fs::create_dir_all(project_root.join("musicxml"))?;
    Ok(())
}

fn project_meta_path(project_root: &Path) -> PathBuf {
    project_root.join("meta.json")
}

fn save_meta(project_root: &Path, meta: &ProjectMeta) -> AppResult<()> {
    let serialized = serde_json::to_vec_pretty(meta)?;
    fs::write(project_meta_path(project_root), serialized)?;
    Ok(())
}

fn load_meta(project_root: &Path) -> AppResult<ProjectMeta> {
    let path = project_meta_path(project_root);
    let raw = fs::read(path)?;
    Ok(serde_json::from_slice(&raw)?)
}

fn create_project_meta(project_id: &str) -> ProjectMeta {
    let timestamp = now_iso();
    ProjectMeta {
        contract_version: CONTRACT_VERSION.to_string(),
        project_id: project_id.to_string(),
        project_name: project_id.to_string(),
        created_at: timestamp.clone(),
        updated_at: timestamp,
        jobs: Vec::new(),
    }
}

fn project_dto_from_meta(project_root: &Path, meta: ProjectMeta) -> ProjectDto {
    ProjectDto {
        id: meta.project_id,
        name: meta.project_name,
        root_path: project_root.to_string_lossy().to_string(),
        created_at: meta.created_at,
        updated_at: meta.updated_at,
    }
}

fn project_root(data_root: &str, project_id: &str) -> PathBuf {
    Path::new(data_root).join(project_id)
}

fn read_settings(state: &SharedState) -> SettingsDto {
    state
        .inner
        .lock()
        .expect("state lock poisoned")
        .settings
        .clone()
}

fn with_job_update<F>(state: &SharedState, job_id: &str, update: F) -> AppResult<JobDto>
where
    F: FnOnce(&mut JobDto),
{
    let mut guard = state.inner.lock().expect("state lock poisoned");
    let job = guard
        .jobs
        .get_mut(job_id)
        .ok_or_else(|| AppError::NotFound(format!("job `{job_id}`")))?;
    update(job);
    Ok(job.clone())
}

fn append_job_log(
    state: &SharedState,
    app: &AppHandle,
    job_id: &str,
    stage: &str,
    level: &str,
    line: &str,
) -> AppResult<()> {
    let entry = JobLogEntryDto {
        timestamp: now_iso(),
        stage: stage.to_string(),
        level: level.to_string(),
        line: line.to_string(),
    };
    with_job_update(state, job_id, |job| {
        job.logs.push(entry.clone());
    })?;
    let _ = app.emit(
        "job:log",
        JobLogEvent {
            job_id: job_id.to_string(),
            stage: stage.to_string(),
            level: level.to_string(),
            line: line.to_string(),
            timestamp: now_iso(),
        },
    );
    Ok(())
}

fn append_stage_warnings(
    state: &SharedState,
    app: &AppHandle,
    job_id: &str,
    stage: &str,
    warnings: &[String],
) -> AppResult<()> {
    for warning in warnings {
        append_job_log(state, app, job_id, stage, "warn", warning)?;
    }
    Ok(())
}

fn emit_progress(app: &AppHandle, job_id: &str, stage: &str, percent: f32, message: &str) {
    let _ = app.emit(
        "job:progress",
        JobProgressEvent {
            job_id: job_id.to_string(),
            stage: stage.to_string(),
            percent,
            message: message.to_string(),
            timestamp: now_iso(),
        },
    );
}

fn emit_state(app: &AppHandle, job_id: &str, state: &str, stage: &str) {
    let _ = app.emit(
        "job:state",
        JobStateEvent {
            job_id: job_id.to_string(),
            state: state.to_string(),
            stage: stage.to_string(),
            timestamp: now_iso(),
        },
    );
}

fn ensure_not_canceled(state: &SharedState, job_id: &str) -> AppResult<()> {
    let guard = state.inner.lock().expect("state lock poisoned");
    let job = guard
        .jobs
        .get(job_id)
        .ok_or_else(|| AppError::NotFound(format!("job `{job_id}`")))?;
    if job.cancel_requested {
        return Err(AppError::Canceled);
    }
    Ok(())
}

fn collect_paths(dir: &Path, extension: &str) -> AppResult<Vec<PathBuf>> {
    let mut values = Vec::new();
    let mut pending = vec![dir.to_path_buf()];
    while let Some(current_dir) = pending.pop() {
        for entry in fs::read_dir(&current_dir)? {
            let path = match entry {
                Ok(entry) => entry.path(),
                Err(_) => continue,
            };
            if path.is_dir() {
                pending.push(path);
                continue;
            }
            let matches_extension = path
                .extension()
                .and_then(|ext| ext.to_str())
                .map(|ext| ext.eq_ignore_ascii_case(extension))
                .unwrap_or(false);
            if matches_extension {
                values.push(path);
            }
        }
    }
    values.sort();
    Ok(values)
}

fn build_transcribe_request(
    project_root: &Path,
    input_path: &Path,
    stem_paths: &[PathBuf],
    output_path: &Path,
    use_placeholders: bool,
    allow_partial_success: bool,
    transcribe_guitar: bool,
    transcribe_other: bool,
    overrides: &ToolPathOverrides,
) -> TranscribeRequest {
    TranscribeRequest {
        contract_version: CONTRACT_VERSION.to_string(),
        project_path: project_root.to_string_lossy().to_string(),
        input_path: input_path.to_string_lossy().to_string(),
        stem_paths: stem_paths
            .iter()
            .map(|path| path.to_string_lossy().to_string())
            .collect(),
        output_path: output_path.to_string_lossy().to_string(),
        options: TranscribeOptions {
            real_execution: !use_placeholders,
            allow_partial_success,
            transcribe_guitar,
            transcribe_other,
            notation_mode: DEFAULT_NOTATION_MODE.to_string(),
            quantization_resolution: DEFAULT_QUANTIZATION_RESOLUTION.to_string(),
            allow_tuplets: false,
            chord_output: DEFAULT_CHORD_OUTPUT.to_string(),
            condition_stems: DEFAULT_CONDITION_STEMS
                .iter()
                .map(|stem| stem.to_string())
                .collect(),
            meter_override: None,
            tool_paths: ToolPathOverrides {
                demucs: None,
                omnizart: overrides.omnizart.clone(),
                basic_pitch: overrides.basic_pitch.clone(),
                musescore: None,
            },
        },
    }
}

fn build_export_musicxml_request(
    project_root: &Path,
    midi_paths: &[PathBuf],
    output_path: &Path,
    use_placeholders: bool,
    allow_partial_success: bool,
    overrides: &ToolPathOverrides,
) -> ExportMusicXmlRequest {
    ExportMusicXmlRequest {
        contract_version: CONTRACT_VERSION.to_string(),
        project_path: project_root.to_string_lossy().to_string(),
        midi_paths: midi_paths
            .iter()
            .map(|path| path.to_string_lossy().to_string())
            .collect(),
        output_path: output_path.to_string_lossy().to_string(),
        options: ExportMusicXmlOptions {
            real_execution: !use_placeholders,
            allow_partial_success,
            tool_paths: ToolPathOverrides {
                demucs: None,
                omnizart: None,
                basic_pitch: None,
                musescore: overrides.musescore.clone(),
            },
        },
    }
}

fn is_text_placeholder(path: &Path) -> bool {
    path.extension()
        .and_then(|ext| ext.to_str())
        .map(|ext| ext.eq_ignore_ascii_case("txt"))
        .unwrap_or(false)
}

fn is_pipeline_media_input(path: &Path) -> bool {
    path.extension()
        .and_then(|ext| ext.to_str())
        .map(|ext| {
            PIPELINE_MEDIA_EXTENSIONS
                .iter()
                .any(|allowed| ext.eq_ignore_ascii_case(allowed))
        })
        .unwrap_or(false)
}

fn select_pipeline_input_path(input_candidates: &[PathBuf]) -> Option<PathBuf> {
    input_candidates
        .iter()
        .find(|path| is_pipeline_media_input(path))
        .cloned()
        .or_else(|| {
            input_candidates
                .iter()
                .find(|path| !is_text_placeholder(path))
                .cloned()
        })
        .or_else(|| input_candidates.first().cloned())
}

fn newest_file_by_prefix(dir: &Path, prefix: &str) -> AppResult<PathBuf> {
    let mut newest: Option<(PathBuf, std::time::SystemTime)> = None;
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let file_name = path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or_default();
        if !file_name.starts_with(prefix) {
            continue;
        }
        let modified = entry
            .metadata()?
            .modified()
            .unwrap_or(std::time::UNIX_EPOCH);
        match &newest {
            None => newest = Some((path, modified)),
            Some((_, timestamp)) if modified > *timestamp => newest = Some((path, modified)),
            _ => {}
        }
    }
    newest.map(|(path, _)| path).ok_or_else(|| {
        AppError::NotFound(format!(
            "no files found in `{}` with prefix `{prefix}`",
            dir.display()
        ))
    })
}

fn download_youtube_input(ytdlp: &str, url: &str, input_dir: &Path) -> AppResult<PathBuf> {
    fs::create_dir_all(input_dir)?;
    let output_template = input_dir.join(format!("{YOUTUBE_INPUT_PREFIX}%(id)s.%(ext)s"));
    let output_template_str = output_template.to_string_lossy().to_string();

    // Demucs stage consumes this file directly, so prefer WAV for maximum compatibility.
    let wav_output = Command::new(ytdlp)
        .arg("--no-playlist")
        .arg("-x")
        .arg("--audio-format")
        .arg("wav")
        .arg("-o")
        .arg(output_template_str.clone())
        .arg(url)
        .output();
    if let Ok(process) = wav_output {
        if process.status.success() {
            return newest_file_by_prefix(input_dir, YOUTUBE_INPUT_PREFIX);
        }
    }

    let output = Command::new(ytdlp)
        .arg("--no-playlist")
        .arg("-f")
        .arg("bestaudio")
        .arg("-o")
        .arg(output_template_str)
        .arg(url)
        .output();
    match output {
        Ok(process) if process.status.success() => {
            newest_file_by_prefix(input_dir, YOUTUBE_INPUT_PREFIX)
        }
        Ok(process) => Err(AppError::Unsupported(format!(
            "yt-dlp failed (wav extraction + bestaudio fallback): {}",
            String::from_utf8_lossy(&process.stderr).trim()
        ))),
        Err(error) => Err(AppError::Unsupported(format!(
            "unable to execute yt-dlp `{ytdlp}`: {error}"
        ))),
    }
}

fn build_runner(
    settings: &SettingsDto,
    use_placeholders: bool,
    diagnostics: Option<JobDiagnostics>,
) -> Box<dyn ToolRunner + Send> {
    if use_placeholders {
        return Box::new(PlaceholderRunner);
    }
    Box::new(CliRunner {
        audio_cli: settings
            .tool_paths
            .audio_cli
            .clone()
            .unwrap_or_else(|| "superscore-audio-cli".to_string()),
        diagnostics,
    })
}

fn tool_path_overrides(settings: &SettingsDto) -> ToolPathOverrides {
    ToolPathOverrides {
        demucs: settings.tool_paths.demucs.clone(),
        omnizart: settings.tool_paths.omnizart.clone(),
        basic_pitch: settings.tool_paths.basic_pitch.clone(),
        musescore: settings.tool_paths.musescore.clone(),
    }
}

fn tool_path_or_default(value: &Option<String>, default: &str) -> String {
    value.clone().unwrap_or_else(|| default.to_string())
}

fn probe_cli_command(command: &str, args: &[&str]) -> AppResult<std::process::Output> {
    Command::new(command).args(args).output().map_err(|error| {
        if error.kind() == std::io::ErrorKind::NotFound {
            AppError::Unsupported(format!(
                "required tool `{command}` not found. Configure this in Settings > Tool Paths or add it to PATH."
            ))
        } else {
            AppError::Unsupported(format!("unable to run tool `{command}`: {error}"))
        }
    })
}

fn ensure_command_probe_ok(
    command: &str,
    args: &[&str],
    tool_name: &str,
    diagnostics: Option<&JobDiagnostics>,
    probe_name: &str,
) -> AppResult<()> {
    let output = match probe_cli_command(command, args) {
        Ok(output) => {
            if let Some(diagnostics) = diagnostics {
                diagnostics.write_preflight_probe_capture(probe_name, command, args, &output)?;
            }
            output
        }
        Err(error) => {
            if let Some(diagnostics) = diagnostics {
                diagnostics.write_preflight_probe_error(
                    probe_name,
                    command,
                    args,
                    &error.to_string(),
                )?;
            }
            return Err(error);
        }
    };
    if output.status.success() {
        return Ok(());
    }
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    if contains_numpy_abi_mismatch(&stderr) {
        return Err(AppError::Unsupported(format!(
            "{tool_name} runtime is incompatible with current NumPy/Torch stack. Use `numpy<2` in the same environment as {tool_name}."
        )));
    }
    let reason = first_non_empty_line(&stderr).unwrap_or_else(|| "unknown failure".to_string());
    Err(AppError::Unsupported(format!(
        "{tool_name} preflight failed: {}",
        compact_error_message(&reason)
    )))
}

fn preflight_demucs_runtime_backend(
    demucs_command: &str,
    diagnostics: Option<&JobDiagnostics>,
) -> AppResult<()> {
    let demucs_path = Path::new(demucs_command);
    let parent = match demucs_path.parent() {
        Some(parent) => parent,
        None => return Ok(()),
    };
    let python = parent.join("python.exe");
    if !path_exists_file(&python) {
        return Ok(());
    }
    let args = [
        "-c",
        "import sys, importlib.util, torchaudio; has_packaging = importlib.util.find_spec('packaging') is not None; has_pkg_resources = importlib.util.find_spec('pkg_resources') is not None; backends = torchaudio.list_audio_backends(); sys.exit(0 if backends and (has_packaging or has_pkg_resources) else (2 if not backends else 3))",
    ];
    let output = match Command::new(&python).args(args).output() {
        Ok(output) => {
            if let Some(diagnostics) = diagnostics {
                diagnostics.write_preflight_probe_capture(
                    "demucs-runtime",
                    &python.to_string_lossy(),
                    &args,
                    &output,
                )?;
            }
            output
        }
        Err(error) => {
            if let Some(diagnostics) = diagnostics {
                diagnostics.write_preflight_probe_error(
                    "demucs-runtime",
                    &python.to_string_lossy(),
                    &args,
                    &error.to_string(),
                )?;
            }
            return Err(AppError::Unsupported(format!(
                "unable to validate demucs runtime with `{}`: {error}",
                python.display()
            )));
        }
    };
    if output.status.success() {
        return Ok(());
    }
    if output.status.code() == Some(2) {
        return Err(AppError::Unsupported(
            "demucs runtime has no available torchaudio backend. Install `soundfile` in the same environment.".to_string(),
        ));
    }
    if output.status.code() == Some(3) {
        return Err(AppError::Unsupported(
            "demucs runtime is missing both `packaging` and `pkg_resources` metadata modules. Install `packaging` (or setuptools providing pkg_resources) in the same environment.".to_string(),
        ));
    }
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    let reason = if contains_numpy_abi_mismatch(&stderr) {
        "demucs runtime NumPy/Torch stack is incompatible".to_string()
    } else {
        last_non_empty_line(&stderr)
            .or_else(|| first_non_empty_line(&stderr))
            .unwrap_or_else(|| "unknown runtime issue".to_string())
    };
    Err(AppError::Unsupported(format!(
        "demucs runtime validation failed: {}",
        compact_error_message(&reason)
    )))
}

fn preflight_real_pipeline(
    settings: &SettingsDto,
    allow_partial_success: bool,
    app: &AppHandle,
    state: &SharedState,
    job_id: &str,
    diagnostics: Option<&JobDiagnostics>,
) -> AppResult<()> {
    let audio_cli = tool_path_or_default(&settings.tool_paths.audio_cli, "superscore-audio-cli");
    let demucs = tool_path_or_default(&settings.tool_paths.demucs, "demucs");
    let basic_pitch = tool_path_or_default(&settings.tool_paths.basic_pitch, "basic-pitch");
    let musescore = tool_path_or_default(&settings.tool_paths.musescore, "musescore");
    let omnizart = tool_path_or_default(&settings.tool_paths.omnizart, "omnizart");

    append_job_log(
        state,
        app,
        job_id,
        "preflight",
        "info",
        "checking audio-cli and tool runtimes",
    )?;

    ensure_command_probe_ok(
        &audio_cli,
        &["--help"],
        "audio-cli",
        diagnostics,
        "audio-cli",
    )?;
    ensure_command_probe_ok(&demucs, &["--help"], "demucs", diagnostics, "demucs")?;
    preflight_demucs_runtime_backend(&demucs, diagnostics)?;
    ensure_command_probe_ok(
        &basic_pitch,
        &["--help"],
        "basic-pitch",
        diagnostics,
        "basic-pitch",
    )?;
    ensure_command_probe_ok(
        &musescore,
        &["--version"],
        "musescore",
        diagnostics,
        "musescore",
    )?;

    let omnizart_result =
        ensure_command_probe_ok(&omnizart, &["--help"], "omnizart", diagnostics, "omnizart");
    match (omnizart_result, allow_partial_success) {
        (Ok(_), _) => {}
        (Err(error), false) => return Err(error),
        (Err(error), true) => {
            append_job_log(
                state,
                app,
                job_id,
                "preflight",
                "warn",
                &format!("omnizart preflight warning (continuing): {}", error),
            )?;
        }
    }
    Ok(())
}

fn to_artifacts(project_id: &str, kind: &str, paths: Vec<PathBuf>) -> Vec<ArtifactDto> {
    paths
        .into_iter()
        .map(|path| ArtifactDto {
            id: Uuid::new_v4().to_string(),
            project_id: project_id.to_string(),
            kind: kind.to_string(),
            path: path.to_string_lossy().to_string(),
            created_at: now_iso(),
        })
        .collect()
}

fn to_stage_artifacts(project_id: &str, artifacts: &[ToolStageArtifact]) -> Vec<ArtifactDto> {
    artifacts
        .iter()
        .map(|artifact| ArtifactDto {
            id: Uuid::new_v4().to_string(),
            project_id: project_id.to_string(),
            kind: artifact.kind.clone(),
            path: artifact.path.to_string_lossy().to_string(),
            created_at: now_iso(),
        })
        .collect()
}

fn record_job_in_meta(data_root: &str, project_id: &str, job: &JobDto) -> AppResult<()> {
    let root = project_root(data_root, project_id);
    let mut meta = load_meta(&root)?;
    meta.updated_at = now_iso();
    meta.jobs.push(JobMeta {
        id: job.id.clone(),
        state: job.state.clone(),
        started_at: job.started_at.clone(),
        finished_at: job.finished_at.clone(),
    });
    save_meta(&root, &meta)?;
    Ok(())
}

fn write_job_summary_snapshot(project_root: &Path, job_id: &str, job: &JobDto) -> AppResult<()> {
    let diagnostics = JobDiagnostics::new(project_root, job_id)?;
    diagnostics.write_summary(job)
}

fn run_pipeline_job(
    app: &AppHandle,
    state: &SharedState,
    data_root: &str,
    project_id: &str,
    job_id: &str,
    options: &RunConfigDto,
) -> AppResult<()> {
    let project_root = project_root(data_root, project_id);
    ensure_project_layout(&project_root)?;
    let diagnostics = JobDiagnostics::new(&project_root, job_id)?;

    let settings = read_settings(state);
    let use_placeholders = options
        .use_placeholders
        .unwrap_or(settings.use_placeholders);
    let allow_partial_success = options.allow_partial_success.unwrap_or(true);
    let transcribe_guitar = options.transcribe_guitar.unwrap_or(true);
    let transcribe_other = options.transcribe_other.unwrap_or(false);
    let runner = build_runner(&settings, use_placeholders, Some(diagnostics.clone()));
    let overrides = tool_path_overrides(&settings);

    let input_dir = project_root.join("input");
    let stems_dir = project_root.join("stems");
    let midi_clean_dir = project_root.join("midi").join("clean");
    let musicxml_dir = project_root.join("musicxml");

    ensure_not_canceled(state, job_id)?;
    if !use_placeholders {
        with_job_update(state, job_id, |job| {
            job.state = "running".to_string();
            job.stage = "preflight".to_string();
            job.progress = 0.03;
        })?;
        emit_state(app, job_id, "running", "preflight");
        emit_progress(
            app,
            job_id,
            "preflight",
            0.03,
            "checking runtime dependencies",
        );
        preflight_real_pipeline(
            &settings,
            allow_partial_success,
            app,
            state,
            job_id,
            Some(&diagnostics),
        )?;
        emit_progress(app, job_id, "preflight", 0.08, "runtime checks passed");
    }

    ensure_not_canceled(state, job_id)?;
    with_job_update(state, job_id, |job| {
        job.state = "running".to_string();
        job.stage = "separate".to_string();
        job.progress = 0.1;
    })?;
    emit_state(app, job_id, "running", "separate");
    emit_progress(app, job_id, "separate", 0.1, "starting separation");
    append_job_log(
        state,
        app,
        job_id,
        "separate",
        "info",
        "running separation stage",
    )?;

    let mut input_candidates: Vec<PathBuf> = fs::read_dir(&input_dir)?
        .filter_map(|entry| entry.ok())
        .map(|entry| entry.path())
        .filter(|path| path.is_file())
        .collect();
    input_candidates.sort_by_key(|path| {
        fs::metadata(path)
            .and_then(|meta| meta.modified())
            .unwrap_or(std::time::UNIX_EPOCH)
    });
    input_candidates.reverse();
    let input_path = select_pipeline_input_path(&input_candidates)
        .ok_or_else(|| AppError::InvalidInput("no input files in project/input".to_string()))?;

    let separate_request = SeparateRequest {
        contract_version: CONTRACT_VERSION.to_string(),
        project_path: project_root.to_string_lossy().to_string(),
        input_path: input_path.to_string_lossy().to_string(),
        output_path: stems_dir.to_string_lossy().to_string(),
        options: SeparateOptions {
            real_execution: !use_placeholders,
            model: select_demucs_model(transcribe_guitar).to_string(),
            tool_paths: ToolPathOverrides {
                demucs: overrides.demucs.clone(),
                omnizart: None,
                basic_pitch: None,
                musescore: None,
            },
        },
    };
    let separate_result = runner.separate(&separate_request)?;
    if separate_result.paths.is_empty() {
        return Err(AppError::Unsupported(
            "separation produced no stem artifacts".to_string(),
        ));
    }
    append_stage_warnings(state, app, job_id, "separate", &separate_result.warnings)?;
    let stem_paths = separate_result.paths;
    let _ = to_artifacts(project_id, "stem", stem_paths.clone());

    ensure_not_canceled(state, job_id)?;
    with_job_update(state, job_id, |job| {
        job.stage = "transcribe".to_string();
        job.progress = 0.55;
    })?;
    emit_progress(app, job_id, "transcribe", 0.55, "starting transcription");
    append_job_log(
        state,
        app,
        job_id,
        "transcribe",
        "info",
        "running transcription stage",
    )?;

    let transcribe_request = build_transcribe_request(
        &project_root,
        &input_path,
        &stem_paths,
        &midi_clean_dir,
        use_placeholders,
        allow_partial_success,
        transcribe_guitar,
        transcribe_other,
        &overrides,
    );
    let transcribe_result = runner.transcribe(&transcribe_request)?;
    if transcribe_result.paths.is_empty() {
        return Err(AppError::Unsupported(
            "transcription produced no midi artifacts".to_string(),
        ));
    }
    append_stage_warnings(
        state,
        app,
        job_id,
        "transcribe",
        &transcribe_result.warnings,
    )?;
    let midi_paths = exportable_midi_paths(&transcribe_result.artifacts);
    let _ = to_stage_artifacts(project_id, &transcribe_result.artifacts);

    ensure_not_canceled(state, job_id)?;
    with_job_update(state, job_id, |job| {
        job.stage = "export".to_string();
        job.progress = 0.85;
    })?;
    emit_progress(app, job_id, "export", 0.85, "starting MusicXML export");
    append_job_log(state, app, job_id, "export", "info", "running export stage")?;

    let export_request = build_export_musicxml_request(
        &project_root,
        &midi_paths,
        &musicxml_dir,
        use_placeholders,
        allow_partial_success,
        &overrides,
    );
    let export_result = runner.export_musicxml(&export_request)?;
    if export_result.paths.is_empty() {
        return Err(AppError::Unsupported(
            "musicxml export produced no artifacts".to_string(),
        ));
    }
    append_stage_warnings(state, app, job_id, "export", &export_result.warnings)?;
    let _ = to_stage_artifacts(project_id, &export_result.artifacts);

    with_job_update(state, job_id, |job| {
        job.state = "completed".to_string();
        job.stage = "done".to_string();
        job.progress = 1.0;
        job.message = Some("pipeline completed".to_string());
        job.finished_at = Some(now_iso());
    })?;
    emit_progress(app, job_id, "done", 1.0, "pipeline completed");
    emit_state(app, job_id, "completed", "done");
    let completed_job = with_job_update(state, job_id, |_| {})?;
    diagnostics.write_summary(&completed_job)?;
    record_job_in_meta(data_root, project_id, &completed_job)?;
    Ok(())
}

async fn run_blocking_command<T, F>(task: F) -> CommandResult<T>
where
    T: Send + 'static,
    F: FnOnce() -> CommandResult<T> + Send + 'static,
{
    tauri::async_runtime::spawn_blocking(task)
        .await
        .map_err(|error| {
            CommandError::from(AppError::Unsupported(format!(
                "background task join failure: {error}"
            )))
        })?
}

fn create_project_sync(name: String, state: SharedState) -> CommandResult<ProjectDto> {
    let project_id = sanitize_project_name(&name)?;
    let settings = read_settings(&state);
    let root = project_root(&settings.data_root, &project_id);

    if root.exists() {
        return Err(AppError::Conflict(format!("project `{project_id}` already exists")).into());
    }

    ensure_project_layout(&root)?;
    let meta = create_project_meta(&project_id);
    save_meta(&root, &meta)?;
    Ok(project_dto_from_meta(&root, meta))
}

#[tauri::command]
async fn create_project(name: String, state: State<'_, SharedState>) -> CommandResult<ProjectDto> {
    let shared = state.inner().clone();
    run_blocking_command(move || create_project_sync(name, shared)).await
}

fn list_projects_sync(state: SharedState) -> CommandResult<Vec<ProjectDto>> {
    let settings = read_settings(&state);
    let data_root = Path::new(&settings.data_root);
    fs::create_dir_all(data_root)?;

    let mut projects = Vec::new();
    for entry in fs::read_dir(data_root)? {
        let entry = entry?;
        if !entry.path().is_dir() {
            continue;
        }
        let meta_path = project_meta_path(&entry.path());
        if !meta_path.exists() {
            continue;
        }
        let meta = load_meta(&entry.path())?;
        projects.push(project_dto_from_meta(&entry.path(), meta));
    }
    projects.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(projects)
}

#[tauri::command]
async fn list_projects(state: State<'_, SharedState>) -> CommandResult<Vec<ProjectDto>> {
    let shared = state.inner().clone();
    run_blocking_command(move || list_projects_sync(shared)).await
}

fn import_local_sync(
    project_id: String,
    file_path: String,
    state: SharedState,
) -> CommandResult<ArtifactDto> {
    let settings = read_settings(&state);
    let root = project_root(&settings.data_root, &project_id);
    if !root.exists() {
        return Err(AppError::NotFound(format!("project `{project_id}`")).into());
    }
    let source = Path::new(&file_path);
    if !source.exists() || !source.is_file() {
        return Err(AppError::InvalidInput(format!("local file not found: {file_path}")).into());
    }
    let filename = source
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| AppError::InvalidInput("invalid local file name".to_string()))?;
    let destination = root.join("input").join(filename);
    fs::copy(source, &destination)?;

    Ok(ArtifactDto {
        id: Uuid::new_v4().to_string(),
        project_id,
        kind: "input".to_string(),
        path: destination.to_string_lossy().to_string(),
        created_at: now_iso(),
    })
}

#[tauri::command]
async fn import_local(
    project_id: String,
    file_path: String,
    state: State<'_, SharedState>,
) -> CommandResult<ArtifactDto> {
    let shared = state.inner().clone();
    run_blocking_command(move || import_local_sync(project_id, file_path, shared)).await
}

fn import_youtube_sync(
    project_id: String,
    url: String,
    state: SharedState,
) -> CommandResult<ArtifactDto> {
    if !(url.starts_with("http://") || url.starts_with("https://")) {
        return Err(
            AppError::InvalidInput("URL must start with http:// or https://".to_string()).into(),
        );
    }
    let settings = read_settings(&state);
    let root = project_root(&settings.data_root, &project_id);
    if !root.exists() {
        return Err(AppError::NotFound(format!("project `{project_id}`")).into());
    }
    let target = if settings.use_placeholders {
        let filename = format!("youtube_{}.txt", Uuid::new_v4());
        let path = root.join("input").join(filename);
        fs::write(&path, format!("placeholder download source\n{url}\n"))?;
        path
    } else {
        let input_dir = root.join("input");
        let ytdlp = settings
            .tool_paths
            .yt_dlp
            .clone()
            .unwrap_or_else(|| "yt-dlp".to_string());
        download_youtube_input(&ytdlp, &url, &input_dir)?
    };

    Ok(ArtifactDto {
        id: Uuid::new_v4().to_string(),
        project_id,
        kind: "input".to_string(),
        path: target.to_string_lossy().to_string(),
        created_at: now_iso(),
    })
}

#[tauri::command]
async fn import_youtube(
    project_id: String,
    url: String,
    state: State<'_, SharedState>,
) -> CommandResult<ArtifactDto> {
    let shared = state.inner().clone();
    run_blocking_command(move || import_youtube_sync(project_id, url, shared)).await
}

fn start_pipeline_sync(
    project_id: String,
    options: Option<RunConfigDto>,
    state: SharedState,
    app: AppHandle,
) -> CommandResult<JobDto> {
    let settings = read_settings(&state);
    let root = project_root(&settings.data_root, &project_id);
    if !root.exists() {
        return Err(AppError::NotFound(format!("project `{project_id}`")).into());
    }
    ensure_project_layout(&root)?;

    let job_id = Uuid::new_v4().to_string();
    let job = JobDto {
        id: job_id.clone(),
        project_id: project_id.clone(),
        state: "queued".to_string(),
        stage: "queued".to_string(),
        progress: 0.0,
        message: Some("job queued".to_string()),
        started_at: now_iso(),
        finished_at: None,
        cancel_requested: false,
        logs: Vec::new(),
    };
    {
        let mut guard = state.inner.lock().expect("state lock poisoned");
        guard.jobs.insert(job_id.clone(), job.clone());
    }

    let app_for_thread = app.clone();
    let state_for_thread = state.clone();
    let project_for_thread = project_id.clone();
    let job_for_thread = job_id.clone();
    let data_root = settings.data_root.clone();
    let run_options = options.unwrap_or_default();
    std::thread::spawn(move || {
        let result = run_pipeline_job(
            &app_for_thread,
            &state_for_thread,
            &data_root,
            &project_for_thread,
            &job_for_thread,
            &run_options,
        );
        if let Err(error) = result {
            let final_state = match error {
                AppError::Canceled => "canceled",
                _ => "failed",
            };
            let message = compact_error_message(&error.to_string());
            let _ = with_job_update(&state_for_thread, &job_for_thread, |job| {
                job.state = final_state.to_string();
                job.progress = 1.0;
                job.finished_at = Some(now_iso());
                job.message = Some(message.clone());
            });
            emit_state(&app_for_thread, &job_for_thread, final_state, "done");
            let _ = append_job_log(
                &state_for_thread,
                &app_for_thread,
                &job_for_thread,
                "done",
                "error",
                &message,
            );
            if let Ok(job) = with_job_update(&state_for_thread, &job_for_thread, |_| {}) {
                let project_root = project_root(&data_root, &project_for_thread);
                let _ = write_job_summary_snapshot(&project_root, &job_for_thread, &job);
                let _ = record_job_in_meta(&data_root, &project_for_thread, &job);
            }
        }
    });

    emit_state(&app, &job_id, "queued", "queued");
    Ok(job)
}

#[tauri::command]
async fn start_pipeline(
    project_id: String,
    options: Option<RunConfigDto>,
    state: State<'_, SharedState>,
    app: AppHandle,
) -> CommandResult<JobDto> {
    let shared = state.inner().clone();
    run_blocking_command(move || start_pipeline_sync(project_id, options, shared, app)).await
}

#[tauri::command]
async fn get_job(job_id: String, state: State<'_, SharedState>) -> CommandResult<JobDto> {
    let guard = state.inner().inner.lock().expect("state lock poisoned");
    let job = guard
        .jobs
        .get(&job_id)
        .ok_or_else(|| AppError::NotFound(format!("job `{job_id}`")))?;
    Ok(job.clone())
}

#[tauri::command]
async fn cancel_job(job_id: String, state: State<'_, SharedState>) -> CommandResult<JobDto> {
    let job = with_job_update(state.inner(), &job_id, |job| {
        job.cancel_requested = true;
        if job.state == "queued" || job.state == "running" {
            job.message = Some("cancel requested".to_string());
        }
    })?;
    Ok(job)
}

#[tauri::command]
async fn list_artifacts(
    project_id: String,
    state: State<'_, SharedState>,
) -> CommandResult<Vec<ArtifactDto>> {
    let shared = state.inner().clone();
    run_blocking_command(move || list_artifacts_sync(project_id, shared)).await
}

fn list_artifacts_sync(project_id: String, state: SharedState) -> CommandResult<Vec<ArtifactDto>> {
    let settings = read_settings(&state);
    let root = project_root(&settings.data_root, &project_id);
    if !root.exists() {
        return Err(AppError::NotFound(format!("project `{project_id}`")).into());
    }

    let mut artifacts = Vec::new();
    let buckets: [(&[&str], &str, Option<&str>); 6] = [
        (&["input"], "input", None),
        (&["stems"], "stem", Some("wav")),
        (&["analysis"], "analysis", Some("json")),
        (&["midi", "raw"], "midi-raw", Some("mid")),
        (&["midi", "clean"], "midi-clean", Some("mid")),
        (&["musicxml"], "musicxml", Some("musicxml")),
    ];
    for (segments, kind, extension) in buckets {
        let path = segments
            .iter()
            .fold(root.clone(), |current, segment| current.join(segment));
        if !path.exists() {
            continue;
        }
        let files = match extension {
            Some(ext) => collect_paths(&path, ext)?,
            None => fs::read_dir(path)?
                .filter_map(|entry| entry.ok())
                .map(|entry| entry.path())
                .filter(|path| path.is_file())
                .collect(),
        };
        artifacts.extend(to_artifacts(&project_id, kind, files));
    }
    artifacts.sort_by(|a, b| a.path.cmp(&b.path));
    Ok(artifacts)
}

#[tauri::command]
async fn get_settings(state: State<'_, SharedState>) -> CommandResult<SettingsDto> {
    Ok(read_settings(state.inner()))
}

#[tauri::command]
async fn update_settings(
    settings: SettingsUpdateDto,
    state: State<'_, SharedState>,
) -> CommandResult<SettingsDto> {
    let shared = state.inner().clone();
    run_blocking_command(move || update_settings_sync(settings, shared)).await
}

fn update_settings_sync(
    settings: SettingsUpdateDto,
    state: SharedState,
) -> CommandResult<SettingsDto> {
    let mut guard = state.inner.lock().expect("state lock poisoned");
    if let Some(data_root) = settings.data_root {
        if data_root.trim().is_empty() {
            return Err(AppError::InvalidInput("data_root cannot be empty".to_string()).into());
        }
        guard.settings.data_root = data_root;
    }
    if let Some(use_placeholders) = settings.use_placeholders {
        guard.settings.use_placeholders = use_placeholders;
    }
    if let Some(tool_paths) = settings.tool_paths {
        guard.settings.tool_paths =
            merge_tool_paths_with_defaults(tool_paths, &ToolPathsDto::default());
    }
    guard.settings = normalize_settings(guard.settings.clone());
    fs::create_dir_all(&guard.settings.data_root)?;
    save_settings_to_disk(&guard.settings)?;
    Ok(guard.settings.clone())
}

pub fn run() {
    tauri::Builder::default()
        .manage(SharedState::default())
        .invoke_handler(tauri::generate_handler![
            create_project,
            list_projects,
            import_local,
            import_youtube,
            start_pipeline,
            get_job,
            cancel_job,
            list_artifacts,
            get_settings,
            update_settings
        ])
        .run(tauri::generate_context!())
        .expect("failed to run SuperScore");
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn sanitize_project_name_replaces_invalid_chars() {
        let sanitized = sanitize_project_name("My Cool:Project!").expect("sanitize should work");
        assert_eq!(sanitized, "My_Cool_Project_");
    }

    #[test]
    fn ensure_project_layout_creates_expected_dirs() {
        let temp = tempdir().expect("tempdir");
        let root = temp.path().join("TestA");
        ensure_project_layout(&root).expect("layout created");
        assert!(root.join("input").exists());
        assert!(root.join("stems").exists());
        assert!(root.join("midi").exists());
        assert!(root.join("musicxml").exists());
    }

    #[test]
    fn creates_analysis_and_split_midi_dirs() {
        let root = tempdir().expect("tempdir");
        ensure_project_layout(root.path()).expect("layout created");

        assert!(root.path().join("analysis").exists());
        assert!(root.path().join("midi").join("raw").exists());
        assert!(root.path().join("midi").join("clean").exists());
    }

    #[test]
    fn transcribe_request_serializes_notation_cleanup_fields() {
        let request = TranscribeRequest {
            contract_version: CONTRACT_VERSION.to_string(),
            project_path: "/project".to_string(),
            input_path: "/project/input/song.wav".to_string(),
            stem_paths: vec!["/project/stems/bass.wav".to_string()],
            output_path: "/project/midi/clean".to_string(),
            options: TranscribeOptions {
                real_execution: false,
                allow_partial_success: true,
                transcribe_guitar: true,
                transcribe_other: false,
                notation_mode: "readable".to_string(),
                quantization_resolution: "1/16".to_string(),
                allow_tuplets: false,
                chord_output: "symbols".to_string(),
                condition_stems: vec![
                    "bass".to_string(),
                    "vocals".to_string(),
                    "guitar".to_string(),
                ],
                meter_override: Some("4/4".to_string()),
                tool_paths: ToolPathOverrides {
                    demucs: None,
                    omnizart: Some("omnizart".to_string()),
                    basic_pitch: Some("basic-pitch".to_string()),
                    musescore: None,
                },
            },
        };

        let serialized = serde_json::to_value(&request).expect("serialize request");
        assert_eq!(
            serialized.get("inputPath").and_then(|value| value.as_str()),
            Some("/project/input/song.wav")
        );
        assert_eq!(
            serialized
                .get("options")
                .and_then(|value| value.get("notationMode"))
                .and_then(|value| value.as_str()),
            Some("readable")
        );
        assert_eq!(
            serialized
                .get("options")
                .and_then(|value| value.get("quantizationResolution"))
                .and_then(|value| value.as_str()),
            Some("1/16")
        );
        assert_eq!(
            serialized
                .get("options")
                .and_then(|value| value.get("allowTuplets"))
                .and_then(|value| value.as_bool()),
            Some(false)
        );
        assert_eq!(
            serialized
                .get("options")
                .and_then(|value| value.get("chordOutput"))
                .and_then(|value| value.as_str()),
            Some("symbols")
        );
        assert_eq!(
            serialized
                .get("options")
                .and_then(|value| value.get("conditionStems"))
                .and_then(|value| value.as_array())
                .map(|values| {
                    values
                        .iter()
                        .filter_map(|value| value.as_str())
                        .collect::<Vec<_>>()
                }),
            Some(vec!["bass", "vocals", "guitar"])
        );
        assert_eq!(
            serialized
                .get("options")
                .and_then(|value| value.get("meterOverride"))
                .and_then(|value| value.as_str()),
            Some("4/4")
        );
    }

    #[test]
    fn cli_runner_transcribe_only_returns_exportable_midi_paths() {
        let temp = tempdir().expect("tempdir");
        let response = serde_json::json!({
            "status": "ok",
            "toolVersion": "test",
            "artifacts": [
                { "kind": "analysis", "path": "C:/project/analysis/beat-grid.json" },
                { "kind": "midi-raw", "path": "C:/project/midi/raw/bass.mid" },
                { "kind": "midi", "path": "C:/project/midi/clean/bass.mid" }
            ],
            "warnings": [],
            "failedArtifacts": []
        })
        .to_string();
        let script = temp.path().join("fake-audio-cli.cmd");
        fs::write(&script, format!("@echo off\r\necho {response}\r\n")).expect("script");

        let runner = CliRunner {
            audio_cli: script.to_string_lossy().to_string(),
            diagnostics: None,
        };
        let result = runner
            .run_subcommand(
                "transcribe",
                &serde_json::json!({ "contractVersion": "v1" }),
            )
            .expect("subcommand response");

        let artifact_kinds = result
            .artifacts
            .iter()
            .map(|artifact| artifact.kind.as_str())
            .collect::<Vec<_>>();
        assert_eq!(artifact_kinds, vec!["analysis", "midi-raw", "midi"]);
        assert_eq!(
            result.paths,
            vec![PathBuf::from("C:/project/midi/clean/bass.mid")]
        );
    }

    #[test]
    fn list_artifacts_exposes_analysis_and_split_midi_kinds() {
        let temp = tempdir().expect("tempdir");
        let state = SharedState::default();
        {
            let mut guard = state.inner.lock().expect("state lock");
            guard.settings.data_root = temp.path().to_string_lossy().to_string();
        }

        let project_id = "ProjectX";
        let root = project_root(&temp.path().to_string_lossy(), project_id);
        ensure_project_layout(&root).expect("layout");
        fs::write(root.join("analysis").join("beat-grid.json"), "{}").expect("analysis");
        fs::write(root.join("midi").join("raw").join("bass.mid"), "raw").expect("raw midi");
        fs::write(root.join("midi").join("clean").join("bass.mid"), "clean").expect("clean midi");

        let artifacts =
            list_artifacts_sync(project_id.to_string(), state).expect("artifact listing");
        let observed = artifacts
            .into_iter()
            .map(|artifact| {
                (
                    artifact.kind,
                    Path::new(&artifact.path)
                        .strip_prefix(&root)
                        .expect("relative path")
                        .to_string_lossy()
                        .replace('\\', "/"),
                )
            })
            .collect::<Vec<_>>();

        assert!(observed.contains(&(
            "analysis".to_string(),
            "analysis/beat-grid.json".to_string(),
        )));
        assert!(observed.contains(&("midi-raw".to_string(), "midi/raw/bass.mid".to_string(),)));
        assert!(observed.contains(&("midi-clean".to_string(), "midi/clean/bass.mid".to_string(),)));
    }

    #[test]
    fn build_transcribe_request_carries_input_path_and_targets_clean_midi() {
        let project_root = PathBuf::from("C:/project");
        let input_path = project_root.join("input").join("song.wav");
        let stem_paths = vec![project_root.join("stems").join("bass.wav")];
        let midi_clean_dir = project_root.join("midi").join("clean");
        let overrides = ToolPathOverrides {
            demucs: None,
            omnizart: Some("omnizart".to_string()),
            basic_pitch: Some("basic-pitch".to_string()),
            musescore: Some("musescore".to_string()),
        };

        let request = build_transcribe_request(
            &project_root,
            &input_path,
            &stem_paths,
            &midi_clean_dir,
            false,
            true,
            true,
            false,
            &overrides,
        );

        assert_eq!(
            request.input_path.replace('\\', "/"),
            "C:/project/input/song.wav"
        );
        assert_eq!(
            request.output_path.replace('\\', "/"),
            "C:/project/midi/clean"
        );
        assert_eq!(request.options.notation_mode, "readable");
    }

    #[test]
    fn meta_roundtrip() {
        let temp = tempdir().expect("tempdir");
        let root = temp.path().join("ProjectX");
        ensure_project_layout(&root).expect("layout");
        let meta = create_project_meta("ProjectX");
        save_meta(&root, &meta).expect("save");
        let loaded = load_meta(&root).expect("load");
        assert_eq!(loaded.project_id, "ProjectX");
        assert_eq!(loaded.contract_version, CONTRACT_VERSION);
    }

    #[test]
    fn pipeline_media_input_detects_expected_extensions() {
        assert!(is_pipeline_media_input(Path::new("song.wav")));
        assert!(is_pipeline_media_input(Path::new("song.WEBM")));
        assert!(is_pipeline_media_input(Path::new("song.mp4")));
        assert!(!is_pipeline_media_input(Path::new("notes.txt")));
        assert!(!is_pipeline_media_input(Path::new(
            "file_without_extension"
        )));
    }

    #[test]
    fn select_pipeline_input_prefers_media_over_placeholder() {
        let candidates = vec![
            PathBuf::from("youtube_random.txt"),
            PathBuf::from("youtube_abc.webm"),
            PathBuf::from("README.md"),
        ];
        let selected = select_pipeline_input_path(&candidates).expect("selected");
        assert_eq!(selected, PathBuf::from("youtube_abc.webm"));
    }

    #[test]
    fn select_pipeline_input_falls_back_when_no_media_exists() {
        let candidates = vec![
            PathBuf::from("youtube_random.txt"),
            PathBuf::from("payload.bin"),
        ];
        let selected = select_pipeline_input_path(&candidates).expect("selected");
        assert_eq!(selected, PathBuf::from("payload.bin"));
    }

    #[test]
    fn numpy_abi_mismatch_detection_matches_known_patterns() {
        assert!(contains_numpy_abi_mismatch(
            "A module that was compiled using NumPy 1.x cannot be run in NumPy 2.2.6"
        ));
        assert!(contains_numpy_abi_mismatch(
            "RuntimeError: Numpy is not available"
        ));
        assert!(!contains_numpy_abi_mismatch("file not found"));
    }

    #[test]
    fn summarize_tool_failure_extracts_nested_message() {
        let stderr =
            r#"{"status":"error","error":{"message":"RuntimeError: Numpy is not available"}}"#;
        let summarized = summarize_tool_failure_stderr(stderr);
        assert!(summarized.contains("NumPy/Torch compatibility mismatch"));
    }

    #[test]
    fn detects_numpy_abi_from_multiline_blob() {
        let stderr =
            "line1\nA module that was compiled using NumPy 1.x cannot be run in NumPy 2.2.6\nline3";
        assert!(contains_numpy_abi_mismatch(stderr));
    }

    #[test]
    fn merge_tool_paths_replaces_command_literal_with_detected_default() {
        let current = ToolPathsDto {
            audio_cli: Some("superscore-audio-cli".to_string()),
            demucs: Some("demucs".to_string()),
            omnizart: Some("omnizart".to_string()),
            basic_pitch: Some("basic-pitch".to_string()),
            musescore: Some("musescore".to_string()),
            yt_dlp: Some("yt-dlp".to_string()),
        };
        let defaults = ToolPathsDto {
            audio_cli: Some("C:\\tool\\superscore-audio-cli.exe".to_string()),
            demucs: Some("C:\\tool\\demucs.exe".to_string()),
            omnizart: Some("C:\\tool\\omnizart.exe".to_string()),
            basic_pitch: Some("C:\\tool\\basic-pitch.exe".to_string()),
            musescore: Some("C:\\tool\\MuseScore4.exe".to_string()),
            yt_dlp: Some("C:\\tool\\yt-dlp.exe".to_string()),
        };
        let merged = merge_tool_paths_with_defaults(current, &defaults);
        assert_eq!(merged.audio_cli, defaults.audio_cli);
        assert_eq!(merged.demucs, defaults.demucs);
        assert_eq!(merged.yt_dlp, defaults.yt_dlp);
    }

    #[test]
    fn merge_tool_paths_keeps_explicit_custom_paths() {
        let current = ToolPathsDto {
            audio_cli: Some("D:\\custom\\audio.exe".to_string()),
            demucs: Some("D:\\custom\\demucs.exe".to_string()),
            omnizart: None,
            basic_pitch: None,
            musescore: None,
            yt_dlp: None,
        };
        let defaults = ToolPathsDto {
            audio_cli: Some("C:\\tool\\superscore-audio-cli.exe".to_string()),
            demucs: Some("C:\\tool\\demucs.exe".to_string()),
            omnizart: Some("C:\\tool\\omnizart.exe".to_string()),
            basic_pitch: Some("C:\\tool\\basic-pitch.exe".to_string()),
            musescore: Some("C:\\tool\\MuseScore4.exe".to_string()),
            yt_dlp: Some("C:\\tool\\yt-dlp.exe".to_string()),
        };
        let merged = merge_tool_paths_with_defaults(current, &defaults);
        assert_eq!(merged.audio_cli, Some("D:\\custom\\audio.exe".to_string()));
        assert_eq!(merged.demucs, Some("D:\\custom\\demucs.exe".to_string()));
        assert_eq!(merged.musescore, defaults.musescore);
    }

    #[test]
    fn demucs_model_selection_uses_six_source_model_for_guitar_transcription() {
        assert_eq!(select_demucs_model(true), "htdemucs_6s");
    }

    #[test]
    fn demucs_model_selection_keeps_four_source_model_without_guitar_transcription() {
        assert_eq!(select_demucs_model(false), "htdemucs");
    }

    #[test]
    fn demucs_model_selection_defaults_to_guitar_compatible_model() {
        let options = RunConfigDto::default();
        let transcribe_guitar = options.transcribe_guitar.unwrap_or(true);

        assert_eq!(select_demucs_model(transcribe_guitar), "htdemucs_6s");
    }

    #[test]
    fn writes_job_diagnostics_bundle() {
        let temp = tempdir().expect("tempdir");
        let diagnostics = JobDiagnostics::new(temp.path(), "job-123").expect("diagnostics");

        diagnostics
            .write_stage_request("separate", &serde_json::json!({ "contractVersion": "v1" }))
            .expect("request");
        diagnostics
            .write_stage_command_capture(
                "separate",
                "audio-cli",
                &[
                    "separate".to_string(),
                    "--request-file".to_string(),
                    "request.json".to_string(),
                ],
                Some(0),
                b"{\"status\":\"ok\"}",
                b"",
            )
            .expect("capture");
        diagnostics
            .write_summary(&serde_json::json!({ "state": "failed", "stage": "separate" }))
            .expect("summary");

        let root = temp.path().join("runs").join("job-123");
        assert!(root.join("separate").join("request.json").exists());
        assert!(root.join("separate").join("stdout.log").exists());
        assert!(root.join("separate").join("command.json").exists());
        assert!(root.join("summary.json").exists());
    }
}
