from dotenv import load_dotenv
from google import genai
from google.genai import types


load_dotenv()

MODEL = "gemini-3.5-flash-lite"

RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=2,
    initial_delay=1,
    max_delay=1,
    http_status_codes=[408, 429, 500, 502, 503, 504],
)


def generate_answer(prompt: str, temperature: float) -> tuple[str, int | None, int | None]:
    client = genai.Client(
        http_options=types.HttpOptions(retry_options=RETRY_OPTIONS)
    )

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