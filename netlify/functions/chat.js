export async function handler(event) {
  try {
    const { prompt, useContext } = JSON.parse(event.body);

    const BASE_URL = "https://burlington-deaths-add-continues.trycloudflare.com";

    let context = "";

    // -----------------------------
    // 1. EMBEDDINGS (optional RAG)
    // -----------------------------
    if (useContext) {
      const embRes = await fetch(`${BASE_URL}/api/embeddings`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: "nomic-embed-text",
          prompt: prompt,
        }),
      });

      const embData = await embRes.json();
      const queryVector = embData.embedding;

      // -----------------------------
      // 2. VECTOR SEARCH (mock for now)
      // Replace this with Chroma / DB
      // -----------------------------
      context = await fakeVectorSearch(queryVector);
    }

    // -----------------------------
    // 3. GENERATION (chat model)
    // -----------------------------
    const finalPrompt = context
      ? `
You are a helpful assistant. Use ONLY the context.

Context:
${context}

Question:
${prompt}
`
      : prompt;

    const genRes = await fetch(`${BASE_URL}/api/generate`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "deepseek-r1:1.5b",
        prompt: finalPrompt,
        stream: false,
      }),
    });

    const genData = await genRes.json();

    return {
      statusCode: 200,
      body: JSON.stringify({
        response: genData.response,
      }),
    };

  } catch (err) {
    return {
      statusCode: 500,
      body: JSON.stringify({
        error: err.message,
      }),
    };
  }
}

// -----------------------------
// TEMP vector search (replace)
// -----------------------------
async function fakeVectorSearch(vector) {
  return "This is retrieved context from your vector database.";
}