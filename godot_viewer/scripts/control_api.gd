extends Node3D

const DEFAULT_PORT := 8790
const WORKSPACE_ROOT := "/workspace"
const DEFAULT_BATCH_RESULT_PATHS := [
	"/workspace/results/person_factory_all_latest.json",
	"/workspace/results/batch_person_factory_in_blender_latest.json",
	"/workspace/results/batch_person_factory_now_latest.json",
]
const GAME_ASSET_DIR := "/workspace/godot_viewer/game_assets"
const GAME_ASSET_GLB_DIR := "/workspace/godot_viewer/game_assets/glb"

var server := TCPServer.new()
var current_character: Node = null
var current_asset_id := ""
var current_glb_path := ""
var assets: Array = []
var extra_batch_result_paths: Array = []
var face_timeline: Dictionary = {}
var face_timeline_index := 0
var face_timeline_started_msec := 0
var face_timeline_source := ""
var face_timeline_duration := 0.0
var face_timeline_cue_count := 0
var face_timeline_expression_count := 0
var active_viseme := "rest"
var active_viseme_value := 0.0
var active_source_phoneme := ""
var active_source_index := -1
var active_expression_preset := "neutral"
var active_expression_value := 0.0

@onready var world: Node3D = $World
@onready var camera: Camera3D = $Camera3D


func _ready() -> void:
	assets = _load_assets()
	var port_text := OS.get_environment("GODOT_CONTROL_PORT")
	var port := int(port_text) if port_text != "" else DEFAULT_PORT
	var err := server.listen(port, "0.0.0.0")
	if err != OK:
		push_error("control api listen failed: %s" % err)
	else:
		print("Godot control API listening on port %s" % port)
	set_process(true)


func _process(_delta: float) -> void:
	_update_face_timeline()
	if not server.is_connection_available():
		return
	var peer := server.take_connection()
	if peer:
		_handle_peer(peer)


func _load_assets() -> Array:
	var output := []
	var seen := {}
	for batch_path in _batch_result_paths():
		output.append_array(_load_assets_from_batch(str(batch_path), seen))
	return output


func _batch_result_paths() -> Array:
	var paths: Array = []
	var env_paths := OS.get_environment("GODOT_BATCH_RESULT_PATHS")
	if env_paths != "":
		for item in env_paths.split(","):
			var path := str(item).strip_edges()
			if path != "":
				paths.append(path)
	else:
		paths.append_array(DEFAULT_BATCH_RESULT_PATHS)
	for path in extra_batch_result_paths:
		if not paths.has(path):
			paths.append(path)
	return paths


func _load_assets_from_batch(batch_path: String, seen: Dictionary) -> Array:
	var file := FileAccess.open(batch_path, FileAccess.READ)
	if not file:
		return []
	var parsed = JSON.parse_string(file.get_as_text())
	if typeof(parsed) != TYPE_DICTIONARY:
		return []
	var output := []
	for job in parsed.get("jobs", []):
		var id := str(job.get("id", ""))
		if id == "" or seen.has(id):
			continue
		seen[id] = true
		var env: Dictionary = job.get("environment", {})
		var metadata: Dictionary = job.get("metadata", {})
		var report_path := str(env.get("ANIMATION_REPORT_JSON", ""))
		var report := _read_animation_report(report_path)
		var glb_path := str(env.get("OUTPUT_GLB", ""))
		var optimized_glb := str(report.get("optimized_glb", ""))
		if optimized_glb != "" and FileAccess.file_exists(optimized_glb):
			glb_path = optimized_glb
		var lipsync_timeline := _lipsync_timeline_path(job, env, report)
		var lipsync_summary := _lipsync_summary(lipsync_timeline)
		output.append({
			"id": id,
			"display_name": metadata.get("display_name", job.get("id", "")),
			"tags": metadata.get("tags", []),
			"persona": metadata.get("persona", ""),
			"glb": glb_path,
			"original_glb": env.get("OUTPUT_GLB", ""),
			"optimized_glb": optimized_glb,
			"lipsync_timeline": lipsync_timeline,
			"lipsync_summary": lipsync_summary,
			"asset_optimization": _asset_optimization_summary(report.get("asset_optimization", {})),
			"report": report_path,
			"status": job.get("status", "unknown")
		})
	return output


func _reload_assets(payload: Dictionary) -> Dictionary:
	var batch_result := str(payload.get("batch_result", ""))
	var scoped := bool(payload.get("scoped", false))
	if scoped and batch_result != "":
		assets = _load_assets_from_batch(batch_result, {})
		return {"status": "ok", "asset_count": assets.size(), "batch_result_paths": [batch_result], "scoped": true}
	if batch_result != "" and not extra_batch_result_paths.has(batch_result):
		extra_batch_result_paths.append(batch_result)
	assets = _load_assets()
	return {"status": "ok", "asset_count": assets.size(), "batch_result_paths": _batch_result_paths(), "scoped": false}


func _read_animation_report(path: String) -> Dictionary:
	if path == "" or not FileAccess.file_exists(path):
		return {}
	var file := FileAccess.open(path, FileAccess.READ)
	if not file:
		return {}
	var parsed = JSON.parse_string(file.get_as_text())
	if typeof(parsed) != TYPE_DICTIONARY:
		return {}
	return parsed


func _asset_optimization_summary(raw_value) -> Dictionary:
	if typeof(raw_value) != TYPE_DICTIONARY:
		return {}
	return {
		"status": raw_value.get("status", ""),
		"source_bytes": raw_value.get("source_bytes", 0),
		"optimized_bytes": raw_value.get("optimized_bytes", 0),
		"saved_bytes": raw_value.get("saved_bytes", 0),
		"size_ratio": raw_value.get("size_ratio", 0.0),
		"warnings": raw_value.get("warnings", []),
		"texture_size": raw_value.get("texture_size", 0),
		"texture_compress": raw_value.get("texture_compress", ""),
		"geometry_compress": raw_value.get("geometry_compress", ""),
	}


func _lipsync_timeline_path(job: Dictionary, env: Dictionary, report: Dictionary) -> String:
	var override_path := str(job.get("lipsync_timeline_override", ""))
	if override_path != "":
		return override_path
	var lipsync = report.get("lipsync_animation", {})
	if typeof(lipsync) == TYPE_DICTIONARY:
		var report_path := str(lipsync.get("timeline", ""))
		if report_path != "":
			return report_path
	var env_path := str(env.get("LIPSYNC_TIMELINE_JSON", ""))
	if env_path != "":
		return env_path
	var job_path := str(job.get("lipsync_timeline_json", ""))
	if job_path != "":
		return job_path
	return ""


func _lipsync_summary(timeline_path: String) -> Dictionary:
	if timeline_path == "" or not FileAccess.file_exists(timeline_path):
		return {"cue_count": 0, "duration": 0.0, "visemes": [], "expression_count": 0}
	var file := FileAccess.open(timeline_path, FileAccess.READ)
	if not file:
		return {"cue_count": 0, "duration": 0.0, "visemes": [], "expression_count": 0}
	var parsed = JSON.parse_string(file.get_as_text())
	if typeof(parsed) != TYPE_DICTIONARY:
		return {"cue_count": 0, "duration": 0.0, "visemes": [], "expression_count": 0}
	var cues: Array = parsed.get("cues", [])
	var expressions: Array = parsed.get("expressions", [])
	var visemes := []
	for cue in cues:
		if typeof(cue) != TYPE_DICTIONARY:
			continue
		var viseme := str(cue.get("viseme", "")).strip_edges()
		if viseme != "" and not visemes.has(viseme):
			visemes.append(viseme)
	var summary := {
		"cue_count": cues.size(),
		"duration": float(parsed.get("duration", 0.0)),
		"visemes": visemes,
		"expression_count": expressions.size(),
	}
	var source_summary := _lipsync_source_summary(parsed, cues)
	for key in source_summary.keys():
		summary[key] = source_summary[key]
	return summary


func _ordered_unique_strings(values) -> Array:
	var output := []
	if typeof(values) != TYPE_ARRAY:
		return output
	for value in values:
		var text := str(value).strip_edges()
		if text != "" and not output.has(text):
			output.append(text)
	return output


func _lipsync_source_summary(timeline: Dictionary, cues: Array) -> Dictionary:
	var raw_source = timeline.get("source", {})
	var source: Dictionary = raw_source if typeof(raw_source) == TYPE_DICTIONARY else {}
	var cue_phonemes := []
	for cue in cues:
		if typeof(cue) != TYPE_DICTIONARY:
			continue
		var phoneme := str(cue.get("source_phoneme", "")).strip_edges()
		if phoneme != "":
			cue_phonemes.append(phoneme)
	var unique_phonemes := _ordered_unique_strings(source.get("unique_phonemes", []))
	if unique_phonemes.is_empty():
		unique_phonemes = _ordered_unique_strings(cue_phonemes)
	var phoneme_counts := {}
	var raw_counts = source.get("phoneme_counts", {})
	if typeof(raw_counts) == TYPE_DICTIONARY:
		for key in raw_counts.keys():
			var phoneme := str(key).strip_edges()
			if phoneme != "":
				phoneme_counts[phoneme] = int(raw_counts[key])
	if phoneme_counts.is_empty():
		for phoneme in unique_phonemes:
			phoneme_counts[phoneme] = cue_phonemes.count(phoneme)
	var event_count := int(source.get("event_count", 0))
	var phoneme_count := int(source.get("phoneme_count", 0))
	if event_count == 0:
		event_count = cue_phonemes.size()
	if phoneme_count == 0:
		for key in phoneme_counts.keys():
			phoneme_count += int(phoneme_counts[key])
		if phoneme_count == 0:
			phoneme_count = event_count
	return {
		"source_mode": str(source.get("mode", "unknown")),
		"source_event_count": event_count,
		"source_phoneme_count": phoneme_count,
		"source_input_mode": str(source.get("input_mode", "")),
		"source_text": str(source.get("text", "")),
		"source_schema": str(source.get("source_schema", "")),
		"source_path": str(source.get("source_path", "")),
		"source_unique_phonemes": unique_phonemes,
		"source_phoneme_counts": phoneme_counts,
	}


func _handle_peer(peer: StreamPeerTCP) -> void:
	peer.poll()
	var request := ""
	var guard := 0
	while peer.get_available_bytes() == 0 and guard < 20:
		OS.delay_msec(5)
		peer.poll()
		guard += 1
	if peer.get_available_bytes() > 0:
		request = peer.get_utf8_string(peer.get_available_bytes())
	var response := _route_request(request)
	peer.put_data(response.to_utf8_buffer())
	peer.disconnect_from_host()


func _route_request(request: String) -> String:
	var lines := request.split("\r\n")
	if lines.is_empty():
		return _json_response(400, {"error": "empty request"})
	var first := lines[0].split(" ")
	if first.size() < 2:
		return _json_response(400, {"error": "bad request"})
	var method := first[0]
	var path := first[1]
	var body := request.substr(request.find("\r\n\r\n") + 4) if request.find("\r\n\r\n") >= 0 else ""
	var payload := {}
	if body.strip_edges() != "":
		var parsed = JSON.parse_string(body)
		if typeof(parsed) == TYPE_DICTIONARY:
			payload = parsed

	if method == "GET" and path == "/health":
		return _json_response(200, {
			"status": "ok",
			"asset_count": assets.size(),
			"loaded": current_asset_id,
			"current_glb": current_glb_path,
			"animations": _animation_names(current_character) if current_character else [],
			"lipsync": _lipsync_playback_status(),
		})
	if method == "GET" and path == "/assets":
		return _json_response(200, {"assets": assets})
	if method == "POST" and path == "/load":
		return _json_response(200, _load_character(str(payload.get("id", ""))))
	if method == "POST" and path == "/animation":
		return _json_response(200, _set_animation(str(payload.get("name", "")), float(payload.get("time", 0.0))))
	if method == "POST" and path == "/expression":
		return _json_response(200, _set_expression(payload))
	if method == "POST" and path == "/expression-preset":
		return _json_response(200, _set_expression_preset(str(payload.get("name", "neutral")), float(payload.get("value", 1.0))))
	if method == "POST" and path == "/viseme":
		return _json_response(200, _set_viseme(str(payload.get("name", "a")), float(payload.get("value", 1.0))))
	if method == "POST" and path == "/speak":
		return _json_response(200, _speak(str(payload.get("text", "")), float(payload.get("value", 1.0))))
	if method == "GET" and path == "/face-profile":
		return _json_response(200, _face_profile())
	if method == "POST" and path == "/lipsync":
		return _json_response(200, _load_lipsync_timeline(payload))
	if method == "POST" and path == "/validate-lipsync-batch":
		return _json_response(200, _validate_lipsync_batch(payload))
	if method == "GET" and path == "/lipsync-status":
		return _json_response(200, _lipsync_playback_status())
	if method == "POST" and path == "/camera":
		return _json_response(200, _set_camera(str(payload.get("preset", "portrait"))))
	if method == "POST" and path == "/render":
		return _json_response(200, _render_png(str(payload.get("path", ""))))
	if method == "POST" and path == "/reload-assets":
		return _json_response(200, _reload_assets(payload))
	if method == "POST" and path == "/export-game-asset":
		return _json_response(200, _export_game_asset(str(payload.get("id", current_asset_id)), bool(payload.get("skip_existing", false))))
	if method == "POST" and path == "/export-all-game-assets":
		return _json_response(200, _export_all_game_assets(payload))
	return _json_response(404, {"error": "not found", "path": path})


func _load_character(asset_id: String) -> Dictionary:
	var asset := _find_asset(asset_id)
	if asset.is_empty():
		return {"status": "error", "error": "unknown asset", "id": asset_id}
	var glb_path := str(asset.get("glb", ""))
	return _load_character_from_glb(asset_id, glb_path, asset)


func _load_character_from_glb(asset_id: String, glb_path: String, asset: Dictionary = {}) -> Dictionary:
	if glb_path == "":
		return {"status": "error", "error": "missing glb path", "id": asset_id}

	if current_character:
		current_character.queue_free()
		current_character = null

	var doc := GLTFDocument.new()
	var state := GLTFState.new()
	var err := doc.append_from_file(glb_path, state)
	if err != OK:
		return {"status": "error", "error": "gltf import failed", "code": err, "path": glb_path}
	current_character = doc.generate_scene(state)
	if not current_character:
		return {"status": "error", "error": "empty generated scene", "path": glb_path}
	world.add_child(current_character)
	current_asset_id = asset_id
	current_glb_path = glb_path
	_reset_lipsync_playback()
	_frame_character("portrait")
	return {
		"status": "ok",
		"id": asset_id,
		"path": glb_path,
		"lipsync_timeline": asset.get("lipsync_timeline", ""),
		"lipsync_summary": asset.get("lipsync_summary", {}),
		"animations": _animation_names(current_character),
	}


func _set_animation(name: String, time: float) -> Dictionary:
	if not current_character:
		return {"status": "error", "error": "no character loaded"}
	var players := _find_animation_players(current_character)
	for player in players:
		if player.has_animation(name):
			player.play(name)
			if time > 0.0:
				player.seek(time, true)
			player.advance(0.0)
			return {"status": "ok", "animation": name, "time": time}
	return {"status": "error", "error": "animation not found", "animation": name, "available": _animation_names(current_character)}


func _set_expression(values: Dictionary) -> Dictionary:
	if not current_character:
		return {"status": "error", "error": "no character loaded"}
	var applied := []
	for mesh in _find_meshes(current_character):
		if not mesh.mesh:
			continue
		var count: int = mesh.mesh.get_blend_shape_count()
		for index in range(count):
			var shape_name: String = str(mesh.mesh.get_blend_shape_name(index))
			for key in values.keys():
				if _shape_matches_key(shape_name, str(key)):
					mesh.set_blend_shape_value(index, float(values[key]))
					applied.append({"mesh": mesh.name, "shape": shape_name.to_lower(), "value": float(values[key])})
	return {"status": "ok", "applied": applied}


func _normalized_shape_name(shape_name: String) -> String:
	return shape_name.to_lower().replace(".", "_").replace("-", "_")


func _shape_matches_key(shape_name: String, key: String) -> bool:
	var normalized := _normalized_shape_name(shape_name)
	var normalized_key := key.to_lower().replace(".", "_").replace("-", "_")
	if ["mth_a", "mth_i", "mth_u", "mth_e", "mth_o"].has(normalized_key):
		return normalized.ends_with("_" + normalized_key) or normalized.find("_" + normalized_key + "_") >= 0
	if normalized_key == "mth":
		return normalized.find("_mth_") >= 0 or normalized.ends_with("_mth")
	return normalized.find(normalized_key) >= 0


func _face_profile() -> Dictionary:
	if not current_character:
		return {"status": "error", "error": "no character loaded"}
	var meshes := []
	var visemes := {}
	var expressions := {}
	for mesh in _find_meshes(current_character):
		if not mesh.mesh:
			continue
		var shapes := []
		var count: int = mesh.mesh.get_blend_shape_count()
		for index in range(count):
			var shape_name := str(mesh.mesh.get_blend_shape_name(index))
			var lower := _normalized_shape_name(shape_name)
			shapes.append(shape_name)
			if _shape_matches_key(shape_name, "mth_a"):
				visemes["aa"] = {"mesh": mesh.name, "shape": shape_name}
			if _shape_matches_key(shape_name, "mth_i"):
				visemes["ih"] = {"mesh": mesh.name, "shape": shape_name}
			if _shape_matches_key(shape_name, "mth_u"):
				visemes["ou"] = {"mesh": mesh.name, "shape": shape_name}
			if _shape_matches_key(shape_name, "mth_e"):
				visemes["ee"] = {"mesh": mesh.name, "shape": shape_name}
			if _shape_matches_key(shape_name, "mth_o"):
				visemes["oh"] = {"mesh": mesh.name, "shape": shape_name}
			if lower.find("eye_close") >= 0 and lower.find("_l") < 0 and lower.find("_r") < 0:
				expressions["blink"] = {"mesh": mesh.name, "shape": shape_name}
			if lower.find("all_joy") >= 0:
				expressions["happy"] = {"mesh": mesh.name, "shape": shape_name}
			if lower.find("all_angry") >= 0:
				expressions["angry"] = {"mesh": mesh.name, "shape": shape_name}
			if lower.find("all_sorrow") >= 0:
				expressions["sad"] = {"mesh": mesh.name, "shape": shape_name}
			if lower.find("all_surprised") >= 0:
				expressions["surprised"] = {"mesh": mesh.name, "shape": shape_name}
		meshes.append({"mesh": mesh.name, "shape_keys": shapes})
	return {
		"status": "ok",
		"schema": "vrm-person-factory.face-profile.v1",
		"id": current_asset_id,
		"meshes": meshes,
		"visemes": visemes,
		"expressions": expressions,
		"quality": {"viseme_count": visemes.size(), "expression_count": expressions.size()},
	}


func _set_expression_preset(name: String, value: float) -> Dictionary:
	var preset := name.strip_edges().to_lower()
	var result: Dictionary = {}
	if preset == "neutral":
		result = _set_expression({"joy": 0.0, "close": 0.0, "mth": 0.0})
	elif preset == "smile" or preset == "joy":
		result = _set_expression({"joy": value, "close": 0.0})
	elif preset == "blink":
		result = _set_expression({"close": value})
	elif preset == "talk":
		result = _set_expression({"joy": value * 0.35, "mth_a": value})
	else:
		return {"status": "error", "error": "unknown expression preset", "preset": name}
	if result.get("status", "") == "ok":
		active_expression_preset = preset
		active_expression_value = value
	result["expression_preset"] = preset
	result["active_expression_preset"] = active_expression_preset
	result["active_expression_value"] = active_expression_value
	return result


func _set_viseme(name: String, value: float) -> Dictionary:
	var viseme: String = name.strip_edges().to_lower()
	var key: String = {
		"a": "mth_a",
		"aa": "mth_a",
		"i": "mth_i",
		"ih": "mth_i",
		"u": "mth_u",
		"ou": "mth_u",
		"e": "mth_e",
		"eh": "mth_e",
		"o": "mth_o",
		"oh": "mth_o",
		"sil": "mth",
		"rest": "mth",
	}.get(viseme, viseme)
	var payload: Dictionary = {}
	if key == "mth":
		payload = {"mth_a": 0.0, "mth_i": 0.0, "mth_u": 0.0, "mth_e": 0.0, "mth_o": 0.0}
	else:
		payload = {"mth_a": 0.0, "mth_i": 0.0, "mth_u": 0.0, "mth_e": 0.0, "mth_o": 0.0}
		payload[key] = value
	var result: Dictionary = _set_expression(payload)
	if result.get("status", "") == "ok":
		active_viseme = viseme
		active_viseme_value = 0.0 if key == "mth" else value
	result["viseme"] = viseme
	result["shape_key_hint"] = key
	result["active_viseme"] = active_viseme
	result["active_viseme_value"] = active_viseme_value
	return result


func _speak(text: String, value: float) -> Dictionary:
	if text.strip_edges() == "":
		return _set_viseme("rest", 0.0)
	var plan: Array = []
	for letter in text.to_lower():
		if "aeiou".contains(letter):
			plan.append(str(letter))
	if plan.is_empty():
		plan.append("rest")
	var result: Dictionary = _set_viseme(str(plan[0]), value)
	result["text"] = text
	result["viseme_plan"] = plan.slice(0, min(plan.size(), 24))
	return result


func _load_lipsync_timeline(payload: Dictionary) -> Dictionary:
	var timeline: Dictionary = {}
	var source := "inline"
	if payload.has("path"):
		var path := str(payload.get("path", ""))
		var file := FileAccess.open(path, FileAccess.READ)
		if not file:
			return {"status": "error", "error": "timeline file missing", "path": path}
		var parsed = JSON.parse_string(file.get_as_text())
		if typeof(parsed) != TYPE_DICTIONARY:
			return {"status": "error", "error": "timeline JSON invalid", "path": path}
		timeline = parsed
		source = path
	elif payload.has("timeline"):
		var direct = payload.get("timeline", {})
		if typeof(direct) == TYPE_DICTIONARY:
			timeline = direct
	if timeline.is_empty():
		return {"status": "error", "error": "missing timeline"}
	var cues: Array = timeline.get("cues", [])
	var expressions: Array = timeline.get("expressions", [])
	face_timeline = timeline
	face_timeline_index = 0
	face_timeline_started_msec = Time.get_ticks_msec()
	face_timeline_source = source
	face_timeline_duration = float(timeline.get("duration", 0.0))
	face_timeline_cue_count = cues.size()
	face_timeline_expression_count = expressions.size()
	_update_face_timeline()
	return {
		"status": "ok",
		"schema": timeline.get("schema", ""),
		"path": source,
		"duration": face_timeline_duration,
		"cue_count": face_timeline_cue_count,
		"expression_count": face_timeline_expression_count,
		"playback": _lipsync_playback_status(),
	}


func _validate_lipsync_batch(payload: Dictionary) -> Dictionary:
	var raw_assets = payload.get("assets", [])
	var checked := []
	var failed := []
	if typeof(raw_assets) != TYPE_ARRAY:
		return {"status": "error", "error": "assets must be an array", "checked": []}
	for item in raw_assets:
		if typeof(item) != TYPE_DICTIONARY:
			var bad := {"status": "review", "issues": ["invalid-asset-payload"]}
			checked.append(bad)
			failed.append(bad)
			continue
		var result := _validate_lipsync_asset(item)
		checked.append(result)
		if result.get("status", "") != "ok":
			failed.append(result)
	return {
		"status": "ok" if failed.is_empty() else "review",
		"checked": checked,
		"checked_count": checked.size(),
		"review_count": failed.size(),
	}


func _missing_profile_visemes(profile: Dictionary, expected: Array) -> Array:
	var missing := []
	var visemes: Dictionary = profile.get("visemes", {}) if typeof(profile.get("visemes", {})) == TYPE_DICTIONARY else {}
	for viseme in expected:
		var key := str(viseme)
		if key != "" and not visemes.has(key):
			missing.append(key)
	return missing


func _missing_timeline_visemes(profile: Dictionary, timeline_visemes: Array) -> Array:
	var missing := []
	var visemes: Dictionary = profile.get("visemes", {}) if typeof(profile.get("visemes", {})) == TYPE_DICTIONARY else {}
	for viseme in timeline_visemes:
		var key := str(viseme)
		if key != "" and key != "rest" and not visemes.has(key):
			missing.append(key)
	return missing


func _validate_lipsync_asset(payload: Dictionary) -> Dictionary:
	var asset_id := str(payload.get("id", ""))
	var glb_path := str(payload.get("glb", ""))
	var timeline := str(payload.get("timeline", ""))
	var expected_cues := int(payload.get("expected_cues", 0))
	var timeline_visemes: Array = payload.get("timeline_visemes", []) if typeof(payload.get("timeline_visemes", [])) == TYPE_ARRAY else []
	var wait_seconds := float(payload.get("wait_seconds", 0.0))
	var issues := []
	var load_result := _load_character_from_glb(asset_id, glb_path, payload) if glb_path != "" else _load_character(asset_id)
	if load_result.get("status", "") != "ok":
		issues.append("load-failed")
	var profile := _face_profile()
	if profile.get("status", "") != "ok":
		issues.append("face-profile-failed")
	var missing_visemes := _missing_profile_visemes(profile, ["aa", "ee", "ih", "oh", "ou"])
	if not missing_visemes.is_empty():
		issues.append("missing-visemes")
	var missing_used_visemes := _missing_timeline_visemes(profile, timeline_visemes)
	if not missing_used_visemes.is_empty():
		issues.append("missing-timeline-visemes")
	var lipsync_result := _load_lipsync_timeline({"path": timeline})
	if lipsync_result.get("status", "") != "ok":
		issues.append("lipsync-start-failed")
	if int(lipsync_result.get("cue_count", 0)) != expected_cues:
		issues.append("cue-count-mismatch")
	if wait_seconds > 0.0:
		OS.delay_msec(int(wait_seconds * 1000.0))
	var playback_status := _lipsync_playback_status()
	var start_status: Dictionary = lipsync_result.get("playback", {}) if typeof(lipsync_result.get("playback", {})) == TYPE_DICTIONARY else {}
	if str(playback_status.get("source", "")) != "" and str(playback_status.get("source", "")) != timeline:
		issues.append("playback-source-mismatch")
	var playback_cue_count := int(playback_status.get("cue_count", 0))
	var start_cue_count := int(start_status.get("cue_count", 0))
	if playback_cue_count != expected_cues and start_cue_count != expected_cues:
		issues.append("playback-cue-count-mismatch")
	if not ["playing", "idle"].has(str(playback_status.get("status", ""))) and not ["playing", "idle"].has(str(start_status.get("status", ""))):
		issues.append("playback-status-invalid")
	return {
		"id": asset_id,
		"status": "ok" if issues.is_empty() else "review",
		"issues": issues,
		"timeline": timeline,
		"cue_count": expected_cues,
		"load": load_result,
		"missing_visemes": missing_visemes,
		"missing_timeline_visemes": missing_used_visemes,
		"lipsync": lipsync_result,
		"playback_status": playback_status,
	}


func _reset_lipsync_playback() -> void:
	face_timeline = {}
	face_timeline_index = 0
	face_timeline_started_msec = 0
	face_timeline_source = ""
	face_timeline_duration = 0.0
	face_timeline_cue_count = 0
	face_timeline_expression_count = 0
	active_viseme = "rest"
	active_viseme_value = 0.0
	active_source_phoneme = ""
	active_source_index = -1
	active_expression_preset = "neutral"
	active_expression_value = 0.0


func _lipsync_playback_status() -> Dictionary:
	var elapsed := 0.0
	var playback_status := "idle"
	if not face_timeline.is_empty() and face_timeline_started_msec > 0:
		elapsed = float(Time.get_ticks_msec() - face_timeline_started_msec) / 1000.0
		playback_status = "playing"
	return {
		"status": playback_status,
		"source": face_timeline_source,
		"duration": face_timeline_duration,
		"elapsed": elapsed,
		"cue_count": face_timeline_cue_count,
		"cue_index": face_timeline_index,
		"expression_count": face_timeline_expression_count,
		"active_viseme": active_viseme,
		"active_viseme_value": active_viseme_value,
		"active_source_phoneme": active_source_phoneme,
		"active_source_index": active_source_index,
		"active_expression_preset": active_expression_preset,
		"active_expression_value": active_expression_value,
	}


func _update_face_timeline() -> void:
	if face_timeline.is_empty():
		return
	var elapsed := float(Time.get_ticks_msec() - face_timeline_started_msec) / 1000.0
	var cues: Array = face_timeline.get("cues", [])
	while face_timeline_index < cues.size():
		var cue: Dictionary = cues[face_timeline_index]
		if elapsed < float(cue.get("time", 0.0)):
			break
		_set_viseme(str(cue.get("viseme", "rest")), float(cue.get("value", 1.0)))
		active_source_phoneme = str(cue.get("source_phoneme", ""))
		active_source_index = int(cue.get("source_index", face_timeline_index))
		face_timeline_index += 1
	for expression in face_timeline.get("expressions", []):
		if typeof(expression) != TYPE_DICTIONARY:
			continue
		var start := float(expression.get("time", 0.0))
		var end := start + float(expression.get("duration", 0.0))
		if elapsed >= start and elapsed <= end:
			_set_expression_preset(str(expression.get("name", "neutral")), float(expression.get("value", 1.0)))
	if elapsed > float(face_timeline.get("duration", 0.0)) + 0.25:
		_set_viseme("rest", 0.0)
		active_source_phoneme = ""
		active_source_index = -1
		face_timeline = {}
		face_timeline_index = face_timeline_cue_count


func _set_camera(preset: String) -> Dictionary:
	_frame_character(preset)
	return {"status": "ok", "preset": preset}


func _render_png(path: String) -> Dictionary:
	if path == "":
		path = "/workspace/outputs/godot/%s.png" % (current_asset_id if current_asset_id != "" else "preview")
	if DisplayServer.get_name() == "headless":
		return {
			"status": "error",
			"error": "headless renderer",
			"detail": "Godot --headless disables rendering/window management. Use Blender pose renders for fast PNG QA, or run Godot with a real display for screenshots.",
			"path": path,
		}
	var viewport_texture := get_viewport().get_texture()
	if not viewport_texture:
		return {
			"status": "error",
			"error": "viewport texture unavailable",
			"detail": "The headless Godot service can import/control/export assets, but PNG capture needs a real renderer. Use Blender pose renders for fast QA.",
			"path": path,
		}
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var image := viewport_texture.get_image()
	if not image:
		return {
			"status": "error",
			"error": "viewport image unavailable",
			"detail": "The headless Godot service is running without a drawable viewport.",
			"path": path,
		}
	var err := image.save_png(path)
	return {"status": "ok" if err == OK else "error", "path": path, "code": err}


func _export_game_asset(asset_id: String, skip_existing: bool = false) -> Dictionary:
	var asset := _find_asset(asset_id)
	if asset.is_empty():
		return {"status": "error", "error": "unknown asset", "id": asset_id}
	var source_glb := str(asset.get("glb", ""))
	if source_glb == "":
		return {"status": "error", "error": "missing glb path", "id": asset_id}
	if not FileAccess.file_exists(source_glb):
		return {"status": "error", "error": "missing glb file", "path": source_glb, "id": asset_id}

	DirAccess.make_dir_recursive_absolute(GAME_ASSET_DIR)
	DirAccess.make_dir_recursive_absolute(GAME_ASSET_GLB_DIR)
	var glb_path := "%s/%s.glb" % [GAME_ASSET_GLB_DIR, asset_id]
	var scene_path := "%s/%s.tscn" % [GAME_ASSET_DIR, asset_id]
	if skip_existing and _game_asset_is_current(source_glb, glb_path, scene_path):
		var scene_size := FileAccess.get_file_as_bytes(scene_path).size()
		return {
			"status": "ok",
			"path": scene_path,
			"glb": glb_path,
			"mode": "referenced-glb",
			"bytes": scene_size,
			"skipped": true,
		}
	var materialization := _link_or_copy_glb(source_glb, glb_path)
	if materialization.get("status", "") == "error":
		return materialization

	var relative_glb := "res://game_assets/glb/%s.glb" % asset_id
	var scene_text := _game_asset_scene_text(asset_id, relative_glb, asset)
	var file := FileAccess.open(scene_path, FileAccess.WRITE)
	if not file:
		return {"status": "error", "error": "scene write failed", "path": scene_path}
	file.store_string(scene_text)
	file.close()
	var size := FileAccess.get_file_as_bytes(scene_path).size()
	return {
		"status": "ok",
		"path": scene_path,
		"glb": glb_path,
		"mode": "referenced-glb",
		"bytes": size,
		"glb_materialization": materialization.get("status", ""),
	}


func _link_or_copy_glb(source_glb: String, glb_path: String) -> Dictionary:
	if FileAccess.file_exists(glb_path):
		DirAccess.remove_absolute(glb_path)
	var output := []
	var link_code := OS.execute("ln", [source_glb, glb_path], output, true)
	if link_code == 0 and FileAccess.file_exists(glb_path):
		return {"status": "linked", "source": source_glb, "path": glb_path}
	var copy_code := DirAccess.copy_absolute(source_glb, glb_path)
	if copy_code != OK:
		return {
			"status": "error",
			"error": "glb copy failed",
			"code": copy_code,
			"link_code": link_code,
			"source": source_glb,
			"path": glb_path,
		}
	return {"status": "copied", "source": source_glb, "path": glb_path}


func _game_asset_is_current(source_glb: String, glb_path: String, scene_path: String) -> bool:
	if not FileAccess.file_exists(source_glb):
		return false
	if not FileAccess.file_exists(glb_path):
		return false
	if not FileAccess.file_exists(scene_path):
		return false
	if FileAccess.get_size(source_glb) != FileAccess.get_size(glb_path):
		return false
	var source_modified := FileAccess.get_modified_time(source_glb)
	var glb_modified := FileAccess.get_modified_time(glb_path)
	var scene_modified := FileAccess.get_modified_time(scene_path)
	return glb_modified >= source_modified and scene_modified >= glb_modified


func _game_asset_scene_text(asset_id: String, relative_glb: String, asset: Dictionary) -> String:
	var safe_name := asset_id.replace("-", "_")
	var tags = asset.get("tags", [])
	var tag_text := ",".join(tags) if typeof(tags) == TYPE_ARRAY else str(tags)
	var lipsync_summary: Dictionary = asset.get("lipsync_summary", {}) if typeof(asset.get("lipsync_summary", {})) == TYPE_DICTIONARY else {}
	var lipsync_visemes = lipsync_summary.get("visemes", [])
	var lipsync_viseme_text := ",".join(lipsync_visemes) if typeof(lipsync_visemes) == TYPE_ARRAY else str(lipsync_visemes)
	var lipsync_source_phonemes = lipsync_summary.get("source_unique_phonemes", [])
	var lipsync_source_phoneme_text := ",".join(lipsync_source_phonemes) if typeof(lipsync_source_phonemes) == TYPE_ARRAY else str(lipsync_source_phonemes)
	return """[gd_scene load_steps=2 format=3]

[ext_resource type="PackedScene" path="%s" id="1_character"]

[node name="%s" instance=ExtResource("1_character")]
metadata/id = "%s"
metadata/display_name = "%s"
metadata/persona = "%s"
metadata/tags = "%s"
metadata/lipsync_timeline = "%s"
metadata/lipsync_cue_count = %d
metadata/lipsync_duration = %.3f
metadata/lipsync_visemes = "%s"
metadata/lipsync_source = "%s"
metadata/lipsync_source_event_count = %d
metadata/lipsync_source_phoneme_count = %d
metadata/lipsync_source_phonemes = "%s"
metadata/animation_report = "%s"
""" % [
		relative_glb,
		safe_name,
		asset_id,
		str(asset.get("display_name", asset_id)).c_escape(),
		str(asset.get("persona", "")).c_escape(),
		tag_text.c_escape(),
		str(asset.get("lipsync_timeline", "")).c_escape(),
		int(lipsync_summary.get("cue_count", 0)),
		float(lipsync_summary.get("duration", 0.0)),
		lipsync_viseme_text.c_escape(),
		str(lipsync_summary.get("source_mode", "unknown")).c_escape(),
		int(lipsync_summary.get("source_event_count", 0)),
		int(lipsync_summary.get("source_phoneme_count", 0)),
		lipsync_source_phoneme_text.c_escape(),
		str(asset.get("report", "")).c_escape(),
	]


func _export_embedded_game_asset(asset_id: String) -> Dictionary:
	if not current_character or asset_id != current_asset_id:
		var load_result := _load_character(asset_id)
		if load_result.get("status") != "ok":
			return load_result
	DirAccess.make_dir_recursive_absolute(GAME_ASSET_DIR)
	var packed := PackedScene.new()
	var err := packed.pack(current_character)
	if err != OK:
		return {"status": "error", "error": "pack failed", "code": err}
	var path := "%s/%s.tscn" % [GAME_ASSET_DIR, asset_id]
	err = ResourceSaver.save(packed, path)
	return {"status": "ok" if err == OK else "error", "path": path, "code": err, "mode": "embedded"}


func _export_all_game_assets(payload: Dictionary = {}) -> Dictionary:
	var skip_existing := bool(payload.get("skip_existing", false))
	var raw_asset_ids = payload.get("asset_ids", [])
	var allowed_asset_ids := []
	if typeof(raw_asset_ids) == TYPE_ARRAY:
		for raw_id in raw_asset_ids:
			var asset_id := str(raw_id)
			if asset_id != "" and not allowed_asset_ids.has(asset_id):
				allowed_asset_ids.append(asset_id)
	var exported := []
	var skipped := []
	var failed := []
	for asset in assets:
		if str(asset.get("status", "")) != "ok":
			continue
		var asset_id := str(asset.get("id", ""))
		if not allowed_asset_ids.is_empty() and not allowed_asset_ids.has(asset_id):
			continue
		var result := _export_game_asset(asset_id, skip_existing)
		if result.get("status") == "ok":
			if result.get("skipped", false):
				skipped.append(result)
			else:
				exported.append(result)
		else:
			failed.append(result)
	return {
		"status": "ok" if failed.is_empty() else "error",
		"exported": exported,
		"skipped": skipped,
		"failed": failed,
		"skip_existing": skip_existing,
		"asset_ids": allowed_asset_ids,
	}


func _find_asset(asset_id: String) -> Dictionary:
	for asset in assets:
		if str(asset.get("id", "")) == asset_id:
			return asset
	return {}


func _find_animation_players(root: Node) -> Array:
	var found := []
	if root is AnimationPlayer:
		found.append(root)
	for child in root.get_children():
		found.append_array(_find_animation_players(child))
	return found


func _find_meshes(root: Node) -> Array:
	var found := []
	if root is MeshInstance3D:
		found.append(root)
	for child in root.get_children():
		found.append_array(_find_meshes(child))
	return found


func _animation_names(root: Node) -> Array:
	var names := []
	for player in _find_animation_players(root):
		for name in player.get_animation_list():
			names.append(str(name))
	return names


func _frame_character(preset: String) -> void:
	var center := Vector3(0, 1.25, 0)
	var distance := 3.2
	if current_character:
		var aabb := _combined_aabb(current_character)
		center = aabb.get_center()
		distance = max(aabb.size.y * (1.25 if preset == "portrait" else 2.7), 2.0)
	if preset == "side":
		camera.global_position = center + Vector3(distance, 0.15, 0.0)
	elif preset == "full":
		camera.global_position = center + Vector3(0, 0.45, distance * 1.25)
	else:
		camera.global_position = center + Vector3(0, 0.12, distance)
	camera.look_at(center, Vector3.UP)


func _combined_aabb(root: Node) -> AABB:
	var has_box := false
	var box := AABB(Vector3.ZERO, Vector3.ONE)
	for mesh in _find_meshes(root):
		var mesh_box: AABB = mesh.get_aabb()
		mesh_box.position = mesh.global_transform * mesh_box.position
		if not has_box:
			box = mesh_box
			has_box = true
		else:
			box = box.merge(mesh_box)
	return box


func _json_response(status_code: int, payload: Dictionary) -> String:
	var status_text := "OK" if status_code < 400 else "ERROR"
	var body := JSON.stringify(payload)
	return "HTTP/1.1 %d %s\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nContent-Length: %d\r\nConnection: close\r\n\r\n%s" % [status_code, status_text, body.to_utf8_buffer().size(), body]
