import json
import os
import re

try:
    import folder_paths
    INPUT_DIR = folder_paths.get_input_directory()
except Exception:  # lets you test outside ComfyUI
    INPUT_DIR = "."


def _get(d, path, default=""):
    """Safe dotted-path lookup: 'request.config.environment_level_information.primary_location'."""
    cur = d
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return default
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur if cur not in (None, "") else default


def _clean(text):
    text = re.sub(r"[*_#>`]", "", str(text))
    text = text.replace("\\n", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _bullets(scenario, heading):
    """Pull bullet lines under a '**Heading**' block of the scenario text."""
    m = re.search(r"\*\*" + re.escape(heading) + r"\*\*(.*?)(?=\n\s*\*\*|\Z)", scenario, re.S)
    if not m:
        return []
    return [_clean(l.lstrip("-• ")) for l in m.group(1).splitlines() if l.strip().startswith(("-", "•"))]


def build_visual_prompt(data, max_behaviors=4):
    cfg = _get(data, "request.config", {})
    char = cfg.get("character_level_information", {})
    env = cfg.get("environment_level_information", {})
    scenario = _get(data, "request.scenario", "") or _get(data, "checkpoint.static_scenario", "")

    low = scenario.lower()
    who = "woman" if "female" in low else "man" if re.search(r"\bmale\b", low) else "person"

    parts = [
        f"Cinematic realistic video, a {char.get('officer_demographics', '')} police officer in uniform "
        f"({char.get('officer_rank', 'patrol officer')}) walks toward a {char.get('person_age', '')}-year-old "
        f"{char.get('person_demographics', '')} {who} at {env.get('primary_location', 'an outdoor location')}, "
        f"{env.get('time_context', '')}.",
        env.get("weather_or_ambient_conditions", ""),
        f"Surroundings: {env.get('stuff_around', '')}",
        f"The {who} is {_get(cfg, 'diversity_plan.presentation_style', '')}.",
    ]
    behaviors = _bullets(scenario, "Observable Behaviors")[:max_behaviors]
    if behaviors:
        parts.append("Body language: " + " ".join(behaviors))
    if env.get("presence_of_weapon", "No").lower() in ("no", "false", ""):
        parts.append("No weapons visible.")
    parts.append("Natural handheld camera, realistic lighting, smooth motion.")
    return _clean(" ".join(p for p in parts if p))


def _scenario_text(data):
    """Narrative only: drops the bold sections (behaviors / dialogue / sensory lists)."""
    s = _get(data, "request.scenario", "") or _get(data, "checkpoint.static_scenario", "")
    s = re.split(r"\n\s*\*\*", s)[0]
    return _clean(s)


class LoadPromptFromJSON:
    MODES = ["auto_visual_prompt", "scenario_narrative", "custom_json_path"]

    @classmethod
    def INPUT_TYPES(cls):
        files = sorted(f for f in os.listdir(INPUT_DIR) if f.lower().endswith(".json")) if os.path.isdir(INPUT_DIR) else []
        return {
            "required": {
                "json_file": (files or ["(put a .json file in ComfyUI/input)"],),
                "mode": (cls.MODES, {"default": "auto_visual_prompt"}),
                "json_path": ("STRING", {"default": "request.scenario"}),
                "prefix": ("STRING", {"default": "", "multiline": True}),
                "suffix": ("STRING", {"default": "", "multiline": True}),
                "max_chars": ("INT", {"default": 1200, "min": 100, "max": 8000}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "load"
    CATEGORY = "utils/prompt"

    def load(self, json_file, mode, json_path, prefix, suffix, max_chars):
        with open(os.path.join(INPUT_DIR, json_file), "r", encoding="utf-8") as f:
            data = json.load(f)

        if mode == "auto_visual_prompt":
            text = build_visual_prompt(data)
        elif mode == "scenario_narrative":
            text = _scenario_text(data)
        else:
            text = _clean(_get(data, json_path, ""))

        text = _clean(f"{prefix} {text} {suffix}")
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0]
        print(f"[LoadPromptFromJSON] {len(text)} chars:\n{text}")
        return (text,)

    @classmethod
    def IS_CHANGED(cls, json_file, **kw):
        p = os.path.join(INPUT_DIR, json_file)
        return os.path.getmtime(p) if os.path.exists(p) else ""



# ---------------------------------------------------------------------------
# Per-turn clip generator
# ---------------------------------------------------------------------------
def _speaker_swap(text, person_name):
    """Make the beat text model-friendly: no names, no 'you', no dialogue."""
    text = _clean(text)
    text = re.sub(r'["\u201c][^"\u201d]*["\u201d]', "", text)  # a video has no dialogue
    seen, sents = set(), []
    for sent in re.split(r"(?<=[.!?])\s+", text):  # drop repeated sentences
        if sent and sent.lower() not in seen:
            seen.add(sent.lower())
            sents.append(sent)
    text = _clean(" ".join(sents))
    first = (person_name or "").split()[0] if person_name else ""
    for n in filter(None, [person_name, first]):
        text = re.sub(re.escape(n), "the woman", text)
    text = re.sub(r"\byour\b", "the officer's", text, flags=re.I)
    text = re.sub(r"\byou\b", "the officer", text, flags=re.I)
    text = re.sub(r"(^|[.!?]\s+)the (woman|officer)", lambda m: m.group(1) + "The " + m.group(2), text)
    return text


def _anchor(data):
    """Same character/location description on every clip -> visual consistency."""
    cfg = _get(data, "request.config", {})
    char = cfg.get("character_level_information", {})
    env = cfg.get("environment_level_information", {})
    scenario = _get(data, "request.scenario", "")
    low = scenario.lower()
    who = "woman" if "female" in low else "man" if re.search(r"\bmale\b", low) else "person"
    return _clean(
        f"Cinematic realistic video. A {char.get('officer_demographics', '')} police officer in uniform and a "
        f"{char.get('person_age', '')}-year-old {char.get('person_demographics', '')} {who} at "
        f"{env.get('primary_location', 'an outdoor location')}, {env.get('time_context', '')}. "
        f"{env.get('weather_or_ambient_conditions', '')} Natural handheld camera, realistic lighting.",
    ), char.get("person_name", "")


def build_turn_clips(data, clip_type="both", turn=0, state_type="all", max_clips=0, use_plan_for_missing=True):
    cp = data.get("checkpoint", {})
    anchor, person = _anchor(data)

    # state_id -> data, from fully written layers (rich text) ...
    layers = {}
    for layer in cp.get("completed_layers", []):
        for st in layer.get("states", []):
            layers[st["id"]] = st
    # ... and from the short-beat plan (covers turns not written out yet)
    plan_turns = cp.get("generation_plan", {}).get("turns", [])

    entries = []  # (turn_number, state_id, kind, prompt, filename)
    for pt in plan_turns:
        tn = pt["turn_number"]
        if turn and tn != turn:
            continue
        for ps in pt.get("states", []):
            sid = ps["state_id"]
            stype = sid.split("_", 1)[1] if "_" in sid else ""
            if state_type != "all" and stype != state_type:
                continue
            rich = layers.get(sid)
            if rich is None and not use_plan_for_missing:
                continue

            # ---- state scene clip
            if clip_type in ("both", "state_scenes"):
                scene = rich["scene"] if rich else f"{ps.get('situation_beat', '')} {ps.get('development_beat', '')}"
                entries.append((tn, sid, "scene", f"{anchor} {_speaker_swap(scene, person)}", f"video/{sid}_scene"))

            # ---- one clip per officer choice
            if clip_type in ("both", "choice_responses"):
                if rich:
                    for ch in rich.get("choices", []):
                        tr = ch.get("transition", {})
                        resp = tr.get("response", {})
                        beat = (f"The officer: {ch.get('text', '')} {resp.get('behavior', '')} "
                                f"{resp.get('body_language', '')} {tr.get('environment_change', '')}")
                        entries.append((tn, sid, "choice", f"{anchor} {_speaker_swap(beat, person)}", f"video/{ch['id']}"))
                else:
                    for ch in ps.get("choices", []):
                        beat = (f"The officer: {ch.get('officer_tactic', '')} {ch.get('response_beat', '')} "
                                f"{ch.get('environment_beat', '')}")
                        entries.append((tn, sid, "choice", f"{anchor} {_speaker_swap(beat, person)}", f"video/{ch['choice_id']}"))

    if max_clips:
        entries = entries[:max_clips]
    return entries


class LoadTurnClipsFromJSON:
    @classmethod
    def INPUT_TYPES(cls):
        files = sorted(f for f in os.listdir(INPUT_DIR) if f.lower().endswith(".json")) if os.path.isdir(INPUT_DIR) else []
        return {
            "required": {
                "json_file": (files or ["(put a .json file in ComfyUI/input)"],),
                "clip_type": (["both", "state_scenes", "choice_responses"], {"default": "both"}),
                "turn": ("INT", {"default": 0, "min": 0, "max": 99}),  # 0 = every turn
                "state_type": (["all", "stabilizing", "uncertain", "escalating"], {"default": "all"}),
                "max_clips": ("INT", {"default": 0, "min": 0, "max": 500}),  # 0 = no limit
                "use_plan_for_missing_turns": ("BOOLEAN", {"default": True}),
                "max_chars": ("INT", {"default": 1200, "min": 100, "max": 8000}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt", "filename_prefix")
    OUTPUT_IS_LIST = (True, True)
    FUNCTION = "load"
    CATEGORY = "utils/prompt"

    def load(self, json_file, clip_type, turn, state_type, max_clips, use_plan_for_missing_turns, max_chars):
        with open(os.path.join(INPUT_DIR, json_file), "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = build_turn_clips(data, clip_type, turn, state_type, max_clips, use_plan_for_missing_turns)
        if not entries:
            raise ValueError("No clips matched these filters.")
        prompts, names = [], []
        for tn, sid, kind, prompt, fname in entries:
            if len(prompt) > max_chars:
                prompt = prompt[:max_chars].rsplit(" ", 1)[0]
            prompts.append(prompt)
            names.append(fname)
            print(f"[LoadTurnClipsFromJSON] turn {tn} | {fname}\n  {prompt}")
        print(f"[LoadTurnClipsFromJSON] {len(prompts)} clips queued")
        return (prompts, names)

    @classmethod
    def IS_CHANGED(cls, json_file, **kw):
        p = os.path.join(INPUT_DIR, json_file)
        return os.path.getmtime(p) if os.path.exists(p) else ""


NODE_CLASS_MAPPINGS = {"LoadPromptFromJSON": LoadPromptFromJSON, "LoadTurnClipsFromJSON": LoadTurnClipsFromJSON}
NODE_DISPLAY_NAME_MAPPINGS = {"LoadPromptFromJSON": "Load Prompt From JSON", "LoadTurnClipsFromJSON": "Load Turn Clips From JSON"}
