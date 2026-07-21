from src.models import CandidateProfile, ParsedDocument
from langchain_core.prompts import ChatPromptTemplate

class CVExtractor:

    def __init__(self, llm,debug=False):
        self.llm = llm.with_structured_output(CandidateProfile)
        self.debug = debug
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """
You are an expert CV information extraction system.

Your task is to extract all relevant information from the CV.

Rules:
- Return only information contained in the CV.
- Never invent information.
- If a field is missing, return null.
- Use the detected hyperlinks whenever they help identify LinkedIn, GitHub, portfolio or personal websites.
- Normalize dates when possible.
- Return a valid CandidateProfile.
- Extract EVERY bullet point.
- Never summarize.
- Never omit relevant information.
- Descriptions and summaries should preserve all technical details.
- If a section contains multiple bullet points,store each one separately.
- Keep technologies exactly as written.
- If a table appears both inline in the CV Markdown and in the Detected tables section, treat the Detected tables version as the authoritative source for that data.
                    """,
                ),
                (
                    "human",
                    """
CV Markdown:

{markdown}

Detected hyperlinks:

{links}

Detected tables:
{tables}
                    """,
                ),
            ]
        )

    def table_to_text(self, tables):
        text = ""
        for table in tables:
            text += "\nDetected table:\n"
            for i, row in enumerate(table.rows):
                text += f"\nRow {i+1}:\n"
                for j, cell in enumerate(row):
                    if cell:
                        text += f"- Column {j+1}: {cell.strip()}\n"
        return text
        
    def extract(self, document: ParsedDocument) -> CandidateProfile:
        chain = self.prompt | self.llm
        if self.debug:
            messages = self.prompt.format_messages(
                markdown=document.content,
                links=document.links,
                tables=document.tables
            )

            with open(
                "debug_prompt.txt",
                "w",
                encoding="utf-8"
            ) as f:
                for msg in messages:
                    f.write(
                        f"\n\n===== {msg.type.upper()} =====\n\n"
                    )
                    f.write(msg.content)

        return chain.invoke({
            "markdown": document.content,
            "links": document.links,
            "tables": self.table_to_text(document.tables)
        })
    
