\# SuperScore



Tauri desktop app for pop-band audio: import → stem separation → transcription → MIDI + MusicXML export.



\## Workflow



1\. Import audio

   - YouTube URL download or local file upload

   - Save to: data\_root/<project\_name>/input/



2\. Source separation

   - Model: Demucs v4 (HTDemucs)

   - Stems: drums / bass / guitar / vocals / other

   - Save WAVs to: data\_root/<project\_name>/stems/



3\. Transcription + export

   - Transcribe each stem to MIDI, then convert to MusicXML

   - Save MIDI to: data\_root/<project\_name>/midi/

   - Save MusicXML to: data\_root/<project\_name>/musicxml/



\## Tech stack (v0)



* Always use pnpm over npm
* Always use uv over pip



\- App: Tauri v2 + Rust

  - project/data folder management

  - job orchestration, progress reporting, logs



\- Audio/ML sidecar: Python CLI tools

  - Separation: demucs (htdemucs)

  - Transcription:

    - drums: Omnizart drum → MIDI

    - vocals/bass: Basic Pitch → MIDI



\- MIDI → MusicXML

  - MuseScore CLI batch convert

  - optional post-process: music21



\## Recommended folder layout



data\_root/

  ProjectA/

    input/

    stems/

    midi/

    musicxml/

    meta.json



\## Final thought:

* Keep the structure and code clear and minimal (but capable of course)
