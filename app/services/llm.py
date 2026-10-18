from dotenv import load_dotenv
from google import genai

load_dotenv()

MODEL = "gemini-3.5-flash-lite"


def generate_answer(prompt: str, temperature: float) -> tuple[str, int | None, int | None]:
    client = genai.Client()
    interaction = client.interactions.create(
        model=MODEL,
        input=prompt,
        generation_config={"temperature": temperature},
        timeout=15,
    )

    if not interaction.output_text:
        raise ValueError("Gemini returned no text")

    usage = interaction.usage
    input_tokens = usage.total_input_tokens if usage else None
    output_tokens = usage.total_output_tokens if usage else None

    return interaction.output_text, input_tokens, output_tokens