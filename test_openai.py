
from dotenv import load_dotenv

# Load API settings from .env
load_dotenv(override=True)

from services.video_generator import generate_educational_scenes


def test_openai():

    print("Testing EduVision OpenAI connection...")

    try:
        result = generate_educational_scenes(
            source_text=(
                "Photosynthesis is the process by which "
                "green plants use sunlight, water and "
                "carbon dioxide to make food. "
                "Plants release oxygen during this process."
            ),
            style="Simple Explanation",
            difficulty="Beginner",
            language="English"
        )

        print("\nOPENAI TEST SUCCESSFUL!")
        print("----------------------------------")

        print("TITLE:", result["title"])
        print("NUMBER OF SCENES:", len(result["scenes"]))

        print("\nGENERATED EDUCATIONAL SCENES")
        print("----------------------------------")

        for index, scene in enumerate(result["scenes"], start=1):

            print(f"\nSCENE {index}")
            print("TITLE:", scene.get("title", "Untitled"))
            print("NARRATION:", scene.get("narration", ""))

        print("\n----------------------------------")
        print("EduVision OpenAI test completed.")

    except Exception as exc:

        print("\nOPENAI TEST FAILED!")
        print("ERROR:", str(exc))


if __name__ == "__main__":
    test_openai()
