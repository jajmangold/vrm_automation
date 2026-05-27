from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lipsync_quality import analyze_lipsync_timeline_path, lipsync_quality_tags


def normalize_tag(value: str) -> str:
    return str(value).strip().lower().replace("_", "-").replace(" ", "-")


def talking_video_metadata(report: dict) -> tuple[str, str]:
    video = str(report.get("talking_video") or "").strip()
    backend = str(report.get("talking_video_backend") or "").strip()
    if video and not backend and "musetalk" in video.lower():
        backend = "musetalk"
    quality = str(report.get("talking_video_quality") or "").strip()
    if video and not quality:
        quality = "preview" if backend == "musetalk" else "available"
    return backend, quality


def workspace_path(value: str, root: Path = ROOT) -> Path:
    if value.startswith("/workspace/"):
        return root / value.removeprefix("/workspace/")
    return Path(value)


def read_job_report(job: dict, root: Path = ROOT) -> dict:
    report_value = job.get("environment", {}).get("ANIMATION_REPORT_JSON")
    if not report_value:
        return {}
    report_path = workspace_path(str(report_value), root)
    if not report_path.exists():
        return {}
    return json.loads(report_path.read_text(encoding="utf-8"))


def job_render_paths(job: dict, root: Path = ROOT) -> list[Path]:
    render_dir = job.get("environment", {}).get("RENDER_DIR")
    if not render_dir:
        return []
    path = workspace_path(str(render_dir), root)
    if not path.exists():
        return []
    return sorted(path.glob("*.png"))


def relative_path(path: Path, output_path: Path) -> str:
    resolved_path = path.resolve()
    resolved_parent = output_path.parent.resolve()
    return (
        resolved_path.relative_to(resolved_parent).as_posix()
        if resolved_path.is_relative_to(resolved_parent)
        else resolved_path.as_posix()
    )


def job_filter_tags(job: dict, report: dict | None = None, root: Path = ROOT) -> list[str]:
    report = report or {}
    metadata = job.get("metadata", {}) if isinstance(job.get("metadata", {}), dict) else {}
    qa = job.get("qa", {}) if isinstance(job.get("qa", {}), dict) else {}
    env = job.get("environment", {}) if isinstance(job.get("environment", {}), dict) else {}
    tags = {normalize_tag(tag) for tag in metadata.get("tags", []) if str(tag).strip()}
    status = str(job.get("status", "")).strip()
    if status:
        tags.add(f"status:{normalize_tag(status)}")
    if qa.get("qa_grade"):
        tags.add(f"qa:{normalize_tag(qa['qa_grade']).upper()}")
    if qa.get("review_priority"):
        tags.add(f"priority:{normalize_tag(qa['review_priority'])}")
    animation = str(report.get("animation") or env.get("ANIMATION_PRESET") or "").strip()
    if animation:
        tags.add(f"animation:{normalize_tag(animation)}")
    lipsync = report.get("lipsync_animation", {}) if isinstance(report.get("lipsync_animation", {}), dict) else {}
    if lipsync.get("enabled"):
        tags.add("lipsync:enabled")
    quality = lipsync_quality_for_report(report, root=root)
    if quality:
        tags.update(lipsync_quality_tags(quality))
    expression = (
        report.get("expression_animation", {})
        if isinstance(report.get("expression_animation", {}), dict)
        else {}
    )
    if expression.get("preset"):
        tags.add(f"face-preset:{normalize_tag(expression['preset'])}")
    if report.get("talking_video"):
        backend, quality = talking_video_metadata(report)
        tags.add("talking-video:available")
        if backend:
            tags.add(f"talking-video-backend:{normalize_tag(backend)}")
        if quality:
            tags.add(f"talking-video-quality:{normalize_tag(quality)}")
    return sorted(tags)


def lipsync_quality_for_report(report: dict, root: Path = ROOT) -> dict:
    lipsync = report.get("lipsync_animation", {}) if isinstance(report.get("lipsync_animation", {}), dict) else {}
    timeline = str(lipsync.get("timeline") or "").strip()
    if not timeline:
        return {}
    return analyze_lipsync_timeline_path(timeline, root=root)


def lipsync_summary_label(report: dict) -> str:
    lipsync = report.get("lipsync_animation", {}) if isinstance(report.get("lipsync_animation", {}), dict) else {}
    if not lipsync.get("enabled"):
        return "off"
    cue_count = int(lipsync.get("cue_count") or 0)
    duration = float(lipsync.get("duration") or 0.0)
    if cue_count and duration:
        return f"{cue_count} cues / {duration:g}s"
    if cue_count:
        return f"{cue_count} cues"
    return "enabled"


def lipsync_source_label(report: dict, root: Path = ROOT) -> str:
    quality = lipsync_quality_for_report(report, root=root)
    if not quality:
        return "none"
    source = str(quality.get("source_mode") or "unknown")
    phoneme_count = int(quality.get("source_phoneme_count", 0) or 0)
    phonemes = quality.get("source_unique_phonemes", [])
    phoneme_text = ", ".join(str(value) for value in phonemes[:8]) if isinstance(phonemes, list) else ""
    pieces = [source]
    if phoneme_count:
        pieces.append(f"{phoneme_count} phonemes")
    if phoneme_text:
        pieces.append(phoneme_text)
    return " / ".join(pieces)


def tag_button(tag: str) -> str:
    return f'<button type="button" class="chip" data-filter="{html.escape(tag, quote=True)}">{html.escape(tag)}</button>'


def build_contact_sheet(batch: dict, output_path: Path, root: Path = ROOT) -> str:
    cards = []
    all_tags: set[str] = set()
    for job in batch.get("jobs", []):
        if job.get("status") != "ok":
            continue
        metadata = job.get("metadata", {})
        report = read_job_report(job, root)
        tags = job_filter_tags(job, report, root=root)
        all_tags.update(tags)
        images = job_render_paths(job, root)
        image_html = "\n".join(
            f'<figure><img src="{html.escape(relative_path(path, output_path))}" loading="lazy"><figcaption>{html.escape(path.name)}</figcaption></figure>'
            for path in images
        )
        display_name = str(metadata.get("display_name") or job.get("id", "unknown"))
        qa = job.get("qa", {}) if isinstance(job.get("qa", {}), dict) else {}
        animation = str(report.get("animation") or job.get("environment", {}).get("ANIMATION_PRESET") or "unknown")
        lip_label = lipsync_summary_label(report)
        lip_source_label = lipsync_source_label(report, root=root)
        video_backend, video_quality = talking_video_metadata(report)
        video_label = " / ".join(value for value in (video_backend, video_quality) if value) or "none"
        search_blob = " ".join(
            [
                str(job.get("id", "unknown")),
                display_name,
                animation,
                lip_label,
                lip_source_label,
                video_label,
                " ".join(tags),
                " ".join(str(note) for note in qa.get("review_notes", [])),
            ]
        ).lower()
        cards.append(
            "\n".join(
                [
                    f'<article class="card" data-tags="{html.escape(" ".join(tags), quote=True)}" data-search="{html.escape(search_blob, quote=True)}">',
                    f'<h2>{html.escape(display_name)}</h2>',
                    f'<div class="id">{html.escape(str(job.get("id", "unknown")))}</div>',
                    '<div class="meta">',
                    f'<span><b>Animation</b>{html.escape(animation)}</span>',
                    f'<span><b>Lip sync</b>{html.escape(lip_label)}</span>',
                    f'<span><b>Lip source</b>{html.escape(lip_source_label)}</span>',
                    f'<span><b>Video</b>{html.escape(video_label)}</span>',
                    f'<span><b>QA</b>{html.escape(str(qa.get("qa_grade", "n/a")))} / {html.escape(str(qa.get("review_priority", "n/a")))}</span>',
                    f'<span><b>Frames</b>{len(images)}</span>',
                    "</div>",
                    f'<div class="tags">{" ".join(f"<span>{html.escape(tag)}</span>" for tag in tags)}</div>',
                    f'<div class="grid">{image_html}</div>',
                    "</article>",
                ]
            )
        )
    chips = "\n".join(tag_button(tag) for tag in sorted(all_tags))
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{html.escape(str(batch.get('manifest', 'Pose Contact Sheet')))}</title>",
            "<style>",
            ":root{color-scheme:dark;--bg:#101214;--panel:#1b1f24;--line:#343a42;--text:#f2eee7;--muted:#aaa6a0;--accent:#72d1c3}",
            "*{box-sizing:border-box} body{font-family:Inter,system-ui,sans-serif;margin:0;background:var(--bg);color:var(--text)}",
            "header{position:sticky;top:0;background:rgba(16,18,20,.96);padding:14px 18px;border-bottom:1px solid var(--line);z-index:1}",
            "main{padding:18px;display:grid;gap:18px}",
            ".toolbar{display:grid;grid-template-columns:minmax(180px,1fr) auto;gap:10px;align-items:start;margin-top:10px}",
            "input{width:100%;border:1px solid var(--line);background:#0c0e10;color:var(--text);border-radius:6px;padding:10px 12px}",
            ".chips{display:flex;gap:7px;flex-wrap:wrap;max-height:84px;overflow:auto}",
            ".chip{border:1px solid var(--line);background:#242a30;color:var(--text);border-radius:6px;padding:8px 10px;cursor:pointer}",
            ".chip.active{background:var(--accent);border-color:var(--accent);color:#071311}",
            ".card{border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:12px}",
            ".card.hidden{display:none}",
            "h1,h2{margin:0 0 8px;letter-spacing:0} .id{color:var(--muted);font-size:13px;margin-bottom:8px}",
            ".meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:1px;background:var(--line);margin:8px 0;border:1px solid var(--line)}",
            ".meta span{display:block;background:#14181c;padding:8px;font-size:12px}.meta b{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;margin-bottom:3px}",
            ".tags{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}.tags span{border:1px solid var(--line);border-radius:5px;color:var(--muted);padding:4px 6px;font-size:12px}",
            ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}",
            "figure{margin:0;background:#24272b;border-radius:6px;overflow:hidden}",
            "img{width:100%;display:block} figcaption{font-size:12px;color:var(--muted);padding:6px 8px}",
            "</style>",
            "</head>",
            "<body>",
            "<header>",
            f"<h1>{html.escape(str(batch.get('manifest', 'Pose Contact Sheet')))}</h1><div><span id=\"visible-count\">{len(cards)}</span> / {len(cards)} jobs</div>",
            f'<div class="toolbar"><input id="contact-search" type="search" placeholder="Search jobs, tags, animations, lip-sync"><div class="chips">{chips}</div></div>',
            "</header>",
            f"<main>{''.join(cards)}</main>",
            "<script>",
            "const search=document.querySelector('#contact-search');const chips=[...document.querySelectorAll('[data-filter]')];const cards=[...document.querySelectorAll('.card')];const count=document.querySelector('#visible-count');const active=new Set();function apply(){const q=(search.value||'').toLowerCase().trim();let visible=0;for(const card of cards){const tags=(card.dataset.tags||'').split(/\\s+/);const matchText=!q||(card.dataset.search||'').includes(q);const matchTags=[...active].every(tag=>tags.includes(tag));const show=matchText&&matchTags;card.classList.toggle('hidden',!show);if(show)visible++;}count.textContent=visible;}chips.forEach(chip=>chip.addEventListener('click',()=>{const tag=chip.dataset.filter;if(active.has(tag)){active.delete(tag);chip.classList.remove('active');}else{active.add(tag);chip.classList.add('active');}apply();}));search.addEventListener('input',apply);",
            "</script>",
            "</body></html>",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a compact HTML QA contact sheet from batch pose renders.")
    parser.add_argument("batch_result", nargs="?", default="results/batch_headwear_refresh_latest.json")
    parser.add_argument("output", nargs="?", default="outputs/batch/pose_contact_sheet.html")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    batch_path = Path(args.batch_result)
    output_path = Path(args.output)
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_contact_sheet(batch, output_path), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    sys.exit(main())
