import pandas as pd


def extract_excel_text(file_path: str) -> str:
    sheets = pd.read_excel(file_path, sheet_name=None)  # dict: {sheet_name: DataFrame}
    text_blocks = []
    for sheet_name, df in sheets.items():
        text_blocks.append(f"[Sheet: {sheet_name}]")
        for _, row in df.iterrows():
            row_text = ", ".join(f"{col}: {val}" for col, val in row.items())
            text_blocks.append(row_text)
    return "\n".join(text_blocks)


def extract_csv_text(file_path: str) -> str:
    df = pd.read_csv(file_path)
    text_blocks = ["[Sheet: csv]"]
    for _, row in df.iterrows():
        row_text = ", ".join(f"{col}: {val}" for col, val in row.items())
        text_blocks.append(row_text)
    return "\n".join(text_blocks)
