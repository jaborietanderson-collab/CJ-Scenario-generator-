# comfyui-json-clip-loader

ComfyUI custom nodes that read a scenario JSON file and generate text-to-video prompts from it.

- **Load Turn Clips From JSON** – one clip per turn: a scene clip for each state plus one clip per officer choice. Outputs a list of prompts and matching filename prefixes.
- **Load Prompt From JSON** – a single prompt from a file (auto visual prompt, scenario narrative, or any dotted JSON path).

## Install (any computer)
1. Open your ComfyUI `custom_nodes` folder.
   - Desktop app: usually `C:\Users\<you>\Documents\ComfyUI\custom_nodes`
2. Run: `git clone <your-repo-url> comfyui-json-clip-loader`
3. Fully restart ComfyUI.
4. Copy your scenario `.json` into ComfyUI's **input** folder (Desktop app: Settings > Storage > Shared Input).
5. Drag `workflows/text_to_video_wan_JSON_API.json` onto the canvas, press `r`, pick the file in `json_file`, Run.

Needs the Wan 2.1 models already used by the workflow (wan2.1_t2v_1.3B_fp16, umt5_xxl_fp8_e4m3fn_scaled, wan_2.1_vae).

## Update
`git pull` inside the folder, then restart ComfyUI.

## Test first
Set `turn` to 1 (4 clips) or `max_clips` to 4 before running everything (136 clips for the sample file).
