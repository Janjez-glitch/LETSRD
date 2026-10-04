import json
import sys
from types import ModuleType, SimpleNamespace

from fastapi.testclient import TestClient

import api
from letsrd_backend.educational_pipeline import GeminiEducationalGenerator


def test_slideshow_generator_applies_selected_illustration_style(monkeypatch, tmp_path):
    captured = {}
    uploaded_file = SimpleNamespace(name="temporary-pdf")
    scenes = [
        {
            "heading": f"Scene {index}",
            "narration": f"Explain concept {index}.",
            "visual_prompt": f"Illustrate concept {index}.",
        }
        for index in range(1, 6)
    ]

    class FakeFiles:
        def upload(self, file):
            return uploaded_file

        def delete(self, name):
            captured["deleted"] = name

    class FakeModels:
        def generate_content(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(
                text=json.dumps(
                    {"title": "Lesson", "summary": "Summary", "slides": scenes}
                )
            )

    google_module = ModuleType("google")
    google_module.genai = SimpleNamespace(
        Client=lambda api_key: SimpleNamespace(files=FakeFiles(), models=FakeModels())
    )
    monkeypatch.setitem(sys.modules, "google", google_module)
    pdf = tmp_path / "notes.pdf"
    pdf.write_bytes(b"pdf")

    GeminiEducationalGenerator("test-key").generate_slideshow_from_pdf(
        pdf, "en", "cinematic"
    )

    assert "realistic cinematic animation" in captured["request"]["contents"][1]
    assert captured["deleted"] == uploaded_file.name


def test_pasted_text_generator_includes_language_style_and_source(monkeypatch):
    captured = {}
    slides = [
        {
            "heading": f"Scene {index}",
            "narration": f"Explain concept {index}.",
            "visual_prompt": f"Illustrate concept {index}.",
            "recall_question": f"What is concept {index}?",
            "recall_choices": ["A", "B", "C"],
            "recall_answer_index": 1,
        }
        for index in range(1, 6)
    ]

    class FakeModels:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                text=json.dumps({"title": "Lesson", "summary": "Summary", "slides": slides})
            )

    google_module = ModuleType("google")
    google_module.genai = SimpleNamespace(
        Client=lambda api_key: SimpleNamespace(models=FakeModels())
    )
    monkeypatch.setitem(sys.modules, "google", google_module)

    result = GeminiEducationalGenerator("test-key").generate_slideshow_from_text(
        "The heart moves blood through the body.", "fr", "infographic"
    )

    assert len(result["slides"]) == 5
    assert "Target narration language: fr" in captured["contents"]
    assert "kinetic infographic" in captured["contents"]
    assert "The heart moves blood" in captured["contents"]
    assert "recall_choices" in captured["config"]["system_instruction"]


def test_slideshow_endpoint_forwards_selected_illustration_style(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.chdir(tmp_path)

    def create_slideshow(self, pdf, tier, language, visual_style):
        captured["visual_style"] = visual_style
        return {
            "job_id": "a" * 32,
            "title": "Lesson",
            "summary": "Summary",
            "scenes": [
                {
                    "heading": "Scene 1",
                    "narration": "Explain the concept.",
                    "visual_prompt": "Illustrate the concept.",
                    "image_filename": "scene-01.png",
                }
            ],
        }

    monkeypatch.setattr(
        api.MediaGeneratorEngine,
        "generate_slideshow_from_pdf",
        create_slideshow,
    )
    response = TestClient(api.app).post(
        "/v1/educational/slideshow",
        files={"file": ("notes.pdf", b"pdf", "application/pdf")},
        data={"visual_style": "infographic"},
    )

    assert response.status_code == 200
    assert captured["visual_style"] == "infographic"


def test_pasted_text_endpoint_forwards_text_language_and_style(monkeypatch):
    captured = {}

    def create_slideshow(self, text, tier, language, visual_style):
        captured.update(text=text, tier=tier, language=language, visual_style=visual_style)
        return {
            "job_id": "c" * 32,
            "title": "Lesson",
            "summary": "Summary",
            "scenes": [
                {
                    "heading": f"Scene {index}",
                    "narration": f"Explain concept {index}.",
                    "visual_prompt": f"Illustrate concept {index}.",
                    "recall_question": "What is the key idea?",
                    "recall_choices": ["A", "B", "C"],
                    "recall_answer_index": 1,
                    "image_filename": f"scene-{index:02}.png",
                }
                for index in range(1, 6)
            ],
        }

    monkeypatch.setattr(
        api.MediaGeneratorEngine,
        "generate_slideshow_from_text",
        create_slideshow,
    )
    response = TestClient(api.app).post(
        "/v1/educational/slideshow/text",
        json={
            "text": "Learner-provided notes.",
            "language": "fr",
            "account_tier": "premium",
            "visual_style": "cinematic",
        },
    )

    assert response.status_code == 200
    assert captured == {
        "text": "Learner-provided notes.",
        "tier": "premium",
        "language": "fr",
        "visual_style": "cinematic",
    }
    assert response.json()["scenes"][0]["recall_choices"] == ["A", "B", "C"]


def test_scene_can_be_regenerated_in_another_learning_style(monkeypatch, tmp_path):
    job_id = "b" * 32
    job_dir = tmp_path / "letsrd_generated" / "slideshows" / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "scene-prompts.json").write_text(
        json.dumps(["A source-grounded heart diagram."]), encoding="utf-8"
    )
    captured = {}

    class FakeImageGenerator:
        def __init__(self, api_key):
            pass

        def generate(self, prompt, output):
            captured["prompt"] = prompt
            output.write_bytes(b"cinematic scene")
            return output

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(api, "GeminiImageGenerator", FakeImageGenerator)
    response = TestClient(api.app).post(
        f"/v1/educational/slideshows/{job_id}/scenes/1/style",
        json={"visual_style": "cinematic"},
    )

    assert response.status_code == 200
    assert "realistic cinematic animation" in captured["prompt"]
    image_url = response.json()["image_url"]
    assert TestClient(api.app).get(image_url).content == b"cinematic scene"


def test_quiz_results_recommend_a_style_after_three_answers(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    client = TestClient(api.app)
    before_threshold = client.post(
        "/v1/learning-style/results",
        json={
            "user_id": "learner@example.test",
            "visual_style": "cinematic",
            "correct": 2,
            "total": 2,
        },
    )
    assert before_threshold.status_code == 200
    assert before_threshold.json()["recommended_style"] is None

    recommendation = client.post(
        "/v1/learning-style/results",
        json={
            "user_id": "learner@example.test",
            "visual_style": "cinematic",
            "correct": 1,
            "total": 1,
        },
    )

    assert recommendation.status_code == 200
    assert recommendation.json()["recommended_style"] == "cinematic"
    assert recommendation.json()["styles"]["cinematic"] == {"correct": 3, "total": 3}
