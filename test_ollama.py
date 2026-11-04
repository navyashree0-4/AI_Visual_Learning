
from services.video_generator import (
    check_ollama_connection,
    generate_ollama_response,
    generate_educational_scenes
)


def main():

    print("\n====================================")
    print("       EDUVISION OLLAMA TEST")
    print("====================================")

    # STEP 1: Check Ollama
    print("\nSTEP 1: Checking Ollama connection...")

    try:

        check_ollama_connection()

        print("SUCCESS: Ollama is connected.")
        
    except Exception as exc:

        print("FAILED:", exc)
        return

    # STEP 2: Test AI response
    print("\nSTEP 2: Testing AI response...")

    try:

        response = generate_ollama_response(
            "Return JSON with a title and a short explanation "
            "of Python programming."
        )

        print("SUCCESS: AI response received.")
        print("\nAI RESPONSE:")
        print(response)

    except Exception as exc:

        print("FAILED:", exc)
        return

    # STEP 3: Test educational scene generation
    print("\nSTEP 3: Generating educational scenes...")

    sample_content = """
    The OSI model is a conceptual framework used to understand
    network communication. It has seven layers:

    1. Physical Layer
    2. Data Link Layer
    3. Network Layer
    4. Transport Layer
    5. Session Layer
    6. Presentation Layer
    7. Application Layer

    Each layer performs a specific function in communication
    between computer systems.
    """

    try:

        result = generate_educational_scenes(
            source_text=sample_content,
            style="Educational",
            difficulty="Beginner",
            language="English"
        )

        print("SUCCESS: Educational scenes generated.")

        print("\nVIDEO TITLE:")
        print(result["title"])

        print("\nSCENES:")

        for index, scene in enumerate(
            result["scenes"],
            start=1
        ):

            print(f"\nSCENE {index}")
            print("Title:", scene["title"])
            print("Narration:", scene["narration"])
            print(
                "Visual:",
                scene["visual_description"]
            )

    except Exception as exc:

        print("FAILED:", exc)
        return

    print("\n====================================")
    print("       ALL OLLAMA TESTS PASSED")
    print("====================================")


if __name__ == "__main__":
    main()
