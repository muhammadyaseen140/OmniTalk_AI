import uuid
from dataclasses import dataclass
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI

CHAT_MODEL = "gpt-4o-mini"

CONDENSE_PROMPT = """Given the chat history and a follow-up question, rewrite the follow-up
as a standalone question. If it is already standalone, return it unchanged.
Return only the question.

Chat history:
{history}

Follow-up question: {question}
Standalone question:"""

ANSWER_PROMPT = """You are an assistant answering questions about a transcript of an audio/video.
Use only the context below. If the answer is not in the context, say you could not find it.

Context:
{context}

Question: {question}
Answer:"""


@dataclass
class RAGSession:
    retriever: object
    llm: object

    def ask(self, question: str, history: list[dict]) -> tuple[str, list[str]]:
        """Answers with chat memory. Returns (answer, source_chunks)."""
        standalone = question
        if history:
            recent = history[-6:]
            hist_text = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
            standalone = self.llm.invoke(
                CONDENSE_PROMPT.format(history=hist_text, question=question)
            ).content.strip()

        docs = self.retriever.invoke(standalone)
        context = "\n\n".join(d.page_content for d in docs)
        answer = self.llm.invoke(ANSWER_PROMPT.format(context=context, question=standalone)).content
        return answer, [d.page_content for d in docs]


def build_rag_session(text: str, api_key: str) -> RAGSession:
    """Splits text, indexes it in its own Chroma collection, returns a RAGSession."""
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_text(text)

    embeddings = OpenAIEmbeddings(model="text-embedding-3-small", api_key=api_key)
    vectorstore = Chroma.from_texts(
        texts=chunks,
        embedding=embeddings,
        metadatas=[{"source": f"chunk_{i}"} for i in range(len(chunks))],
        collection_name=f"session_{uuid.uuid4().hex}",  # unique, so sessions never mix
    )
    retriever = vectorstore.as_retriever(search_kwargs={"k": 4})
    llm = ChatOpenAI(model=CHAT_MODEL, temperature=0, api_key=api_key)
    return RAGSession(retriever=retriever, llm=llm)


def generate_summary(text: str, api_key: str) -> str:
    """Map-reduce summary: works for very long transcripts."""
    llm = ChatOpenAI(model=CHAT_MODEL, temperature=0.3, api_key=api_key)
    splitter = RecursiveCharacterTextSplitter(chunk_size=12000, chunk_overlap=300)
    parts = splitter.split_text(text)

    if len(parts) == 1:
        return llm.invoke(
            f"Write a concise executive summary with key points:\n\n{parts[0]}"
        ).content

    partials = [
        llm.invoke(f"Summarize this part of a transcript in a few bullet points:\n\n{p}").content
        for p in parts
    ]
    combined = "\n\n".join(partials)
    return llm.invoke(
        f"Combine these partial summaries into one concise executive summary with key points:\n\n{combined}"
    ).content
