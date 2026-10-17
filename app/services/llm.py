from dotenv import load_dotenv
from google import genai

load_dotenv()


def generate_answer(prompt: str, temperature: float) -> str:
    client = genai.Client()
    interaction = client.interactions.create(
        model="gemini-3.5-flash-lite",
        input=prompt,
        generation_config={"temperature": temperature},
        timeout=15,
    )
    return interaction.output_text