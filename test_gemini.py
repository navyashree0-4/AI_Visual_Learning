import os
from dotenv import dotenv_values
from google import genai

# Read API key directly from .env
config = dotenv_values(".env")
api_key = config.get("GEMINI_API_KEY")

print("API key found:", bool(api_key))

if not api_key:
    print("ERROR: Gemini API key not found")
    exit()

# Connect to Gemini
client = genai.Client(api_key=api_key)

print("Connecting to Gemini...")

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Explain the OSI model in 3 simple sentences."
)

print("\nGemini Response:")
print(response.text)