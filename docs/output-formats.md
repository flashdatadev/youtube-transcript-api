# Transcript output formats

All exports run locally from a `Transcript`. Fetch once and reuse it.

| Format | Contents |
| --- | --- |
| `json` | Video/language metadata, complete text, timestamped segments |
| `txt` | Complete caption text followed by a newline |
| `srt` | Numbered subtitle cues; `HH:MM:SS,mmm` timestamps |
| `vtt` | `WEBVTT` header and `HH:MM:SS.mmm` timestamps |
| `csv` | One row per caption; video ID, language, start, end, text |
| `md` | One caption per bullet, with a source timestamp link |

Times are seconds in JSON and CSV. SRT and VTT round to the nearest millisecond. A cue that rounds to zero duration is extended to one millisecond for valid subtitle playback. Blank cue text is omitted in subtitles; JSON and CSV preserve it. Blank lines and markup in caption text are escaped for subtitle formats. Original overlapping segments are not deduplicated.

JSON uses the toolkit's normalized snake_case model. The raw API uses fields such as `videoId` and `languageCode`; they are mapped by `Transcript.from_api()`. To reload a saved toolkit export:

```python
import json
from pathlib import Path
from flashdata_transcript import Transcript, render

transcript = Transcript.from_dict(json.loads(Path("transcript.json").read_text(encoding="utf-8")))
print(render(transcript, "srt"))
```

`fetch-languages` produces a **result envelope** with `tracks` and `errors`. Select an individual item from `tracks` before passing it to `Transcript.from_dict()` or converting it. Likewise, successful collection rows contain tracks under `row["result"]["tracks"]`; they are not single-transcript exports.

CSV preserves original text, including any leading formula characters. If opening untrusted caption text in a spreadsheet, import the text column as text rather than interpreting formulas.

The synthetic demo marks `is_demo: true` and uses `source_url: null`. Live exports retain the YouTube source URL. Chunk timestamps refer to source segments, not generated word alignment.
