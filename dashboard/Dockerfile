FROM python:latest

EXPOSE 8501

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY .streamlit/ .streamlit/
COPY assets/ assets/
COPY .env .

COPY dashboard.py .
COPY data_functions.py .
COPY ai_summary_functions.py .
COPY dynamodb_functions.py .
    
CMD streamlit run dashboard.py