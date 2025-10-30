from dotenv import load_dotenv
import os
import google.generativeai as genai
import oracledb
import re
import sqlparse

# Load environment variables
load_dotenv()

# Gemini setup
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.0-flash')

# Config: Toggle debug mode
DEBUG = False  # Set to True for logging

# Customize with your DB schema, including relationships
DB_SCHEMA = """
Tables:
- rule: Columns include rule_id (NUMBER), rule_set_id (NUMBER, foreign key to rule_set), description (VARCHAR2).
- rule_set: Columns include rule_set_id (NUMBER, primary key), rulename (VARCHAR2).
- property: Columns include id (NUMBER), address (VARCHAR2), price (NUMBER).  # Add your other tables here
Relationships: rule joins rule_set on rule_set_id.
Query USER_TAB_COLUMNS for schemas, USER_CONSTRAINTS for constraints.
"""

# Database connection
def get_db_connection():
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    dsn = os.getenv("DB_DSN")
    try:
        return oracledb.connect(user=user, password=password, dsn=dsn)
    except oracledb.Error as e:
        raise Exception(f"Database connection failed: {e}")

# ...existing code...

def extract_sql(text):
    """
    Removes code block markers (``` and ```sql) and trailing semicolons from a string and returns only the SQL query.
    """
    lines = [line for line in text.splitlines() if not line.strip().lower().startswith("```")]
    sql = "\n".join(lines).strip()
    # Remove any trailing semicolons
    sql = re.sub(r';\s*$', '', sql)
    return sql

def validate_sql(sql):
    # forbidden_patterns = [
    #     r"\bDROP\b", r"\bTRUNCATE\b", r"\bALTER\b", r"\bCREATE\b",
    #     r"\bDELETE\b(?!.*WHERE)", r"\bUPDATE\b(?!.*WHERE)",
    #     r"\bINSERT\b", r";"
    # ]
    # for pattern in forbidden_patterns:
    #     if re.search(pattern, sql, re.IGNORECASE):
    #         return False, f"Disallowed pattern: {pattern}"

    sql = extract_sql(sql)  # Clean up code block markers
    if not sql.strip().upper().startswith("SELECT"):
        return False, "Only SELECT queries are allowed."

    parsed = sqlparse.parse(sql)
    if len(parsed) > 1:
        return False, "Multiple statements not allowed."
    for token in parsed[0].tokens:
        if token.ttype is sqlparse.tokens.DML and token.value.upper() != "SELECT":
            return False, "Non-SELECT DML not allowed."

    return True, "Valid", sql

# Execute SQL with formatting and pagination
def execute_sql(sql):
    is_valid, message, query = validate_sql(sql)
    print(query)
    # is_valid, message = True, "Valid"
    if not is_valid:
        raise Exception(f"Validation failed: {message}")

    with get_db_connection() as connection:
        cursor = connection.cursor()
        try:
            cursor.execute(query)
            if cursor.description:
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                if len(rows) > 10:
                    rows = rows[:10]
                    note = "\n(Note: Showing first 10 rows; more results available.)"
                else:
                    note = ""
                header = "| " + " | ".join(columns) + " |\n"
                separator = "| " + " | ".join(["---"] * len(columns)) + " |\n"
                body = "".join("| " + " | ".join(str(item) if item is not None else 'NULL' for item in row) + " |\n" for row in rows)
                return header + separator + body + note
            connection.commit()
            return "Operation successful."
        except oracledb.Error as e:
            raise Exception(f"Execution failed: {e}")

# Intent detection
def detect_intent(user_query):
    prompt = f"""
    Classify as 'chat' or 'db'. Return only 'chat' or 'db'.
    Examples:
    - "Show first 5 from PROPERTY" => db
    - "Rule descriptions and rule names" => db
    - "Tell me a joke" => chat
    Query: {user_query}
    """
    response = model.generate_content(prompt)
    intent = response.text.strip().lower()
    return intent if intent in ['chat', 'db'] else 'chat'

# Generate SQL with multi-table support
def generate_sql(user_query):
    prompt = f"""
    Oracle SQL expert: Convert to clean SQL.
    Rules:
    - Schemas: USER_TAB_COLUMNS for columns/types.
    - Joins: INNER JOIN on shared columns like rule_set_id for multi-table.
    - Limits: ROWNUM <= n.
    - Constraints: USER_CONSTRAINTS if requested.
    - No DESC/DESCRIBE. UPPER() for case-insensitivity.
    - ONLY the SQL.
    Examples:
    - "Rule descriptions and rule names": SELECT r.description, rs.rulename FROM rule r INNER JOIN rule_set rs ON r.rule_set_id = rs.rule_set_id
    - "Schema for rule": SELECT COLUMN_NAME, DATA_TYPE, DATA_LENGTH, NULLABLE FROM USER_TAB_COLUMNS WHERE TABLE_NAME = UPPER('RULE')
    - "First 5 from property": SELECT * FROM property WHERE ROWNUM <= 5
    Database: {DB_SCHEMA}
    Query: {user_query}
    """
    response = model.generate_content(prompt)
    return response.text.strip()

# Handle chat
def handle_chat(user_query):
    prompt = f"Respond helpfully: {user_query}"
    response = model.generate_content(prompt)
    return response.text.strip()

# Main assistant function
def chat_assistant(user_input):
    if not user_input.strip():
        return "Enter a query."
    intent = detect_intent(user_input)
    if DEBUG:
        print(f"[DEBUG] Intent: {intent}")
    if intent == 'db':
        try:
            sql = generate_sql(user_input)
            if DEBUG:
                print(f"[DEBUG] SQL: {sql}")
            results = execute_sql(sql)
            return f"DB Results:\n{results}"
        except Exception as e:
            # Intelligent error explanation
            explain_prompt = f"Explain this error simply: {str(e)}"
            explanation = model.generate_content(explain_prompt).text.strip()
            return f"Error: {explanation}"
    return handle_chat(user_input)

# Console main
def console_main():
    print("Welcome! Type 'exit' to quit.")
    while True:
        user_input = input("\nYou: ").strip()
        if user_input.lower() == 'exit':
            print("Goodbye!")
            break
        print(f"Assistant: {chat_assistant(user_input)}")

# Optional Streamlit UI (uncomment to enable)
import streamlit as st
def streamlit_main():
    st.title("AI Chat Assistant")
    user_input = st.text_input("Your query:")
    if st.button("Submit"):
        st.write(chat_assistant(user_input))

if __name__ == "__main__":
    console_main()  # Switch to streamlit_main() for web UI