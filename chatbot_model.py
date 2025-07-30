import pandas as pd
import google.generativeai as genai
import re
from langdetect import detect, DetectorFactory

DetectorFactory.seed = 0  # to make language detection consistent

# Gemini API key
GEMINI_API_KEY = "AIzaSyDXB538kTAfi6dILexYffuoXrmEhXl8hqc"
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

def is_urdu(text):
    """Detect Urdu language using Unicode and langdetect (for Roman Urdu)."""
    try:
        lang = detect(text)
    except:
        lang = ""
    
    urdu_chars = re.findall(r'[\u0600-\u06FF]', text)
    has_urdu_script = len(urdu_chars) > 5
    is_probably_roman_urdu = lang in ["ur", "hi", "fa"]  # Urdu, Hindi, Persian often match Roman Urdu
    
    return has_urdu_script or is_probably_roman_urdu

def format_response(response_text):
    """Format the response for better readability"""
    # If the response contains a list of items, format them with proper line breaks
    if re.search(r'\d+\.\s+\w+.*?:\s+[\d,]+', response_text):
        # Split by the pattern "number. name: value" and add line breaks
        formatted = re.sub(r'(\d+\.\s+[^:]+:\s+[\d,]+\s*\w*)', r'\n\1', response_text)
        # Remove any leading/trailing whitespace and ensure single line breaks
        formatted = re.sub(r'\n\s*', '\n', formatted).strip()
        return formatted
    return response_text

def get_chat_response(user_message, df):
    try:
        # Detect language
        urdu_requested = is_urdu(user_message)
        language_instruction = (
            "جواب صرف اردو میں دیں۔ انگریزی استعمال نہ کریں۔\n\n" if urdu_requested else ""
        )
        
        # Create a summary of the entire dataset
        columns = df.columns.tolist()
        row_count = len(df)
        
        # For large datasets, we'll create a more efficient representation
        if row_count > 100:
            # Create a summary of the dataset with statistics
            summary = {
                "total_rows": row_count,
                "columns": columns,
                "numeric_columns": df.select_dtypes(include=['number']).columns.tolist(),
                "categorical_columns": df.select_dtypes(include=['object']).columns.tolist(),
            }
            
            # Add basic statistics for numeric columns
            if summary["numeric_columns"]:
                stats = df[summary["numeric_columns"]].describe().to_dict()
                summary["statistics"] = stats
            
            # For ranking questions, process directly in Python
            if "top" in user_message.lower() and ("player" in user_message.lower() or "run" in user_message.lower()):
                # Extract the number of players requested
                match = re.search(r'top\s+(\d+)', user_message.lower())
                n = int(match.group(1)) if match else 5
                
                # Find the runs column
                runs_column = None
                for col in columns:
                    if 'run' in col.lower():
                        runs_column = col
                        break
                
                if runs_column:
                    # Make sure the column is numeric
                    if df[runs_column].dtype == 'object':
                        # Try to convert to numeric, removing any non-numeric characters
                        df[runs_column] = pd.to_numeric(df[runs_column].astype(str).str.replace('[^\d.]', '', regex=True), errors='coerce')
                    
                    # Sort by the column in descending order and get top n
                    top_players = df.sort_values(by=runs_column, ascending=False).head(n)
                    
                    # Format the result
                    result = f"Top {n} players by {runs_column}:\n\n"
                    for i, (_, row) in enumerate(top_players.iterrows(), 1):
                        player_name = row.get('Player', row.get('Name', f"Player {i}"))
                        value = row[runs_column]
                        # Format with commas for thousands
                        formatted_value = "{:,}".format(int(value)) if pd.notna(value) and value != '' else "N/A"
                        result += f"{i}. {player_name}: {formatted_value}\n\n"
                    
                    return result.strip()
            
            # For other questions with large datasets, use a summary approach
            prompt = f"""
You are a cricket data analyst. Answer the user's question based on the cricket dataset.

DATASET SUMMARY:
- Total records: {summary['total_rows']}
- Columns: {', '.join(summary['columns'])}
- Numeric columns: {', '.join(summary['numeric_columns']) if summary['numeric_columns'] else 'None'}
- Categorical columns: {', '.join(summary['categorical_columns']) if summary['categorical_columns'] else 'None'}

STATISTICS:
{summary.get('statistics', 'No statistics available')}

{language_instruction}

IMPORTANT: Provide a concise, direct answer. Format your response clearly with line breaks between different points.

User Question: "{user_message}"
"""
            
            response = model.generate_content(prompt)
            return format_response(response.text)
        
        else:
            # For small datasets (<= 100 rows), send the entire dataset
            full_data = df.to_dict(orient='records')
            
            prompt = f"""
You are a cricket data analyst. Answer the user's question based on the complete cricket dataset.

COMPLETE DATASET:
{full_data}

{language_instruction}

IMPORTANT: Provide a concise, direct answer. Format your response clearly with line breaks between different points.

User Question: "{user_message}"
"""
            
            response = model.generate_content(prompt)
            return format_response(response.text)
        
    except Exception as e:
        if "429" in str(e):
            return "Error: API quota exceeded. Please try again later."
        return f"Error generating response: {str(e)}"