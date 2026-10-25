import httpx
import streamlit as st


API_URL = "http://127.0.0.1:8000"


def call_api(method: str, path: str, api_key: str, json=None):
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        response = httpx.request(
            method=method,
            url=f"{API_URL}{path}",
            headers=headers,
            json=json,
            timeout=20,
        )
    except httpx.RequestError:
        st.error("Could not connect to the gateway.")
        return None

    if response.status_code >= 400:
        st.error(f"Gateway returned HTTP {response.status_code}")
        st.json(response.json())
        return None

    return response


st.set_page_config(page_title="LLM Gateway", page_icon="🤖")
st.title("LLM Gateway Dashboard")

api_key = st.text_input("API key", type="password")

st.subheader("Chat")

prompt = st.text_area("Prompt")
temperature = st.slider(
    "Temperature",
    min_value=0.0,
    max_value=2.0,
    value=0.7,
    step=0.1,
)

if st.button("Send"):
    if not api_key:
        st.warning("Enter your API key.")
    elif not prompt:
        st.warning("Enter a prompt.")
    else:
        response = call_api(
            method="POST",
            path="/chat",
            api_key=api_key,
            json={
                "prompt": prompt,
                "temperature": temperature,
            },
        )

        if response is not None:
            data = response.json()

            st.success("Answer received")
            st.write(data["answer"])

            st.caption(
                f"Model: {data['model']} | "
                f"Latency: {data['latency_ms']} ms | "
                f"Cache: {response.headers.get('X-Cache', 'UNKNOWN')} | "
                f"Request ID: {response.headers.get('X-Request-ID', 'UNKNOWN')}"
            )

st.subheader("Usage")

if st.button("Load usage"):
    if not api_key:
        st.warning("Enter your API key.")
    else:
        response = call_api(
            method="GET",
            path="/usage",
            api_key=api_key,
        )

        if response is not None:
            usage = response.json()

            column1, column2, column3 = st.columns(3)

            column1.metric("Requests", usage["request_count"])
            column2.metric("Errors", usage["error_count"])
            column3.metric("Cache hits", usage["cache_hits"])

            st.json(usage)

st.subheader("Recent requests")

if st.button("Load recent requests"):
    if not api_key:
        st.warning("Enter your API key.")
    else:
        response = call_api(
            method="GET",
            path="/usage/recent?limit=20&offset=0",
            api_key=api_key,
        )

        if response is not None:
            data = response.json()
            st.dataframe(data["items"], width="stretch")