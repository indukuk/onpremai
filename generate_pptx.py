"""
Generate a PowerPoint presentation using Claude API Agent Skills (pptx skill).

Usage:
    export ANTHROPIC_API_KEY=your-key-here
    pip install anthropic
    python generate_pptx.py

Requires: anthropic SDK, ANTHROPIC_API_KEY env var
Beta features: code-execution-2025-08-25, skills-2025-10-02
"""

import os
import sys
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("Install the Anthropic SDK: pip install anthropic")
    sys.exit(1)

if not os.environ.get("ANTHROPIC_API_KEY"):
    print("Set your API key: export ANTHROPIC_API_KEY=sk-ant-...")
    sys.exit(1)

PITCH_CONTENT = Path("pitch-deck-slides.md").read_text()

PROMPT = f"""Create a professional PowerPoint presentation based on the following pitch deck content.
Make it visually compelling with:
- Dark theme (navy/dark blue backgrounds, green/teal accent color #00d4aa)
- Clean modern typography
- Diagrams and architecture visuals where applicable
- Professional slide layouts with proper spacing

Here is the full pitch deck content to convert into slides:

{PITCH_CONTENT}
"""

client = anthropic.Anthropic()

print("Calling Claude API with pptx skill (this may take 30-60 seconds)...")

response = client.beta.messages.create(
    model="claude-opus-4-8",
    max_tokens=16000,
    betas=["code-execution-2025-08-25", "skills-2025-10-02"],
    container={
        "skills": [{"type": "anthropic", "skill_id": "pptx", "version": "latest"}]
    },
    messages=[{"role": "user", "content": PROMPT}],
    tools=[{"type": "code_execution_20250825", "name": "code_execution"}],
)

print(f"Response received: stop_reason={response.stop_reason}, blocks={len(response.content)}")

file_id = None
for block in response.content:
    if block.type == "code_execution_tool_result":
        if block.content.type == "code_execution_result":
            for output in block.content.content:
                if hasattr(output, "file_id") and output.file_id:
                    file_id = output.file_id
    elif block.type == "bash_code_execution_tool_result":
        if block.content.type == "bash_code_execution_result":
            for output in block.content.content:
                if hasattr(output, "file_id") and output.file_id:
                    file_id = output.file_id

if file_id:
    output_path = Path("pitch-deck-ai-generated.pptx")
    file_content = client.beta.files.download(file_id=file_id)
    file_content.write_to_file(output_path)
    print(f"\nPresentation saved to: {output_path}")
    print(f"File size: {output_path.stat().st_size / 1024:.1f} KB")
else:
    print("\nNo file was generated. Response content:")
    for block in response.content:
        if block.type == "text":
            print(block.text[:500])
