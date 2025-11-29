import streamlit as st
import google.generativeai as genai
import os
from dotenv import load_dotenv
import json
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore, storage
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import PyPDF2
from docx import Document
import pandas as pd

# ============================================================================
# PART 1: SETUP & INITIALIZATION
# ============================================================================

load_dotenv()

API_KEY = os.getenv("GOOGLE_API_KEY")

# ============================================================================
# PDF & DOCX EXTRACTION
# ============================================================================

def extract_text_from_pdf(pdf_file):
    """
    Extract text from PDF file
    Uses PyPDF2 library
    """
    try:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text.strip()
    except Exception as e:
        st.error(f"Error reading PDF: {str(e)}")
        return None

def extract_text_from_docx(docx_file):
    """
    Extract text from DOCX (Word) file
    Uses python-docx library
    """
    try:
        doc = Document(docx_file)
        text = ""
        for para in doc.paragraphs:
            text += para.text + "\n"
        return text.strip()
    except Exception as e:
        st.error(f"Error reading DOCX: {str(e)}")
        return None

def extract_text_from_txt(txt_file):
    """
    Extract text from plain text file
    """
    try:
        text = txt_file.read().decode("utf-8")
        return text.strip()
    except Exception as e:
        st.error(f"Error reading TXT: {str(e)}")
        return None

def process_resume_file(uploaded_file):
    """
    Universal resume processor - handles PDF, DOCX, TXT
    Returns extracted text
    """
    file_extension = uploaded_file.name.split('.')[-1].lower()
    
    if file_extension == 'pdf':
        return extract_text_from_pdf(uploaded_file)
    elif file_extension == 'docx':
        return extract_text_from_docx(uploaded_file)
    elif file_extension == 'txt':
        return extract_text_from_txt(uploaded_file)
    else:
        st.error(f"❌ Unsupported file format: {file_extension}. Use PDF, DOCX, or TXT")
        return None

# ============================================================================
# FIREBASE INITIALIZATION (Cloud Storage & Database)
# ============================================================================

def get_firebase_creds():
    firebase_env = os.getenv("FIREBASE_CREDENTIALS")
    if firebase_env and os.path.exists(firebase_env):
        try:
            with open(firebase_env, 'r') as f:
                return json.load(f)
        except:
            return None
    return None

def initialize_firebase():
    """Initialize Firebase connection"""
    try:
        if not firebase_admin.get_app():
            firebase_creds = get_firebase_creds()
            if firebase_creds:
                creds = credentials.Certificate(firebase_creds)
                firebase_admin.initialize_app(creds)
        return firestore.client()
    except:
        return None

def save_screening_results_to_firebase(db, results, job_description, company_name):
    """Save screening results to Firestore database"""
    try:
        screening_data = {
            'timestamp': datetime.now(),
            'job_description': job_description,
            'company_name': company_name,
            'total_candidates': len(results),
            'results': results,
            'top_candidate': results[0]['candidate_name'] if results else None,
            'top_candidate_score': results[0]['match_score'] if results else 0
        }
        
        doc_ref = db.collection('screenings').document()
        doc_ref.set(screening_data)
        
        st.success(f"✅ Results saved to Firebase! Document ID: {doc_ref.id}")
        return doc_ref.id
    
    except Exception as e:
        st.warning(f"Could not save to Firebase: {str(e)}")
        return None

def upload_resume_to_storage(storage_bucket, candidate_name, resume_text):
    """Upload resume text to Firebase Cloud Storage"""
    try:
        bucket = storage.bucket(storage_bucket)
        filename = f"resumes/{candidate_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        blob = bucket.blob(filename)
        blob.upload_from_string(resume_text)
        st.info(f"📁 Resume uploaded: {filename}")
        return filename
    except Exception as e:
        st.warning(f"Could not upload to storage: {str(e)}")
        return None

# ============================================================================
# GOOGLE CALENDAR INITIALIZATION
# ============================================================================

def get_calendar_creds():
    calendar_env = os.getenv("GOOGLE_CALENDAR_CREDENTIALS")
    if calendar_env and os.path.exists(calendar_env):
        try:
            with open(calendar_env, 'r') as f:
                return json.load(f)
        except:
            return None
    return None

def initialize_google_calendar():
    """Initialize Google Calendar API"""
    try:
        calendar_creds = get_calendar_creds()
        if calendar_creds:
            creds = Credentials.from_service_account_info(calendar_creds)
            service = build('calendar', 'v3', credentials=creds)
            return service
        return None
    except:
        return None

def schedule_interview_on_calendar(calendar_service, candidate_email, candidate_name, job_title, interview_date, interview_time, meeting_link=""):
    """
    Schedule interview on Google Calendar
    Sends invite to candidate with meeting details
    """
    try:
        # Combine date and time
        datetime_obj = datetime.strptime(f"{interview_date} {interview_time}", "%Y-%m-%d %H:%M")
        start_time = datetime_obj.isoformat()
        end_time = (datetime_obj + timedelta(hours=1)).isoformat()
        
        event = {
            'summary': f'Interview - {job_title} with {candidate_name}',
            'description': f'Interview for {job_title} position\n\nCandidate: {candidate_name}\n\nMeeting Link: {meeting_link}',
            'start': {
                'dateTime': start_time,
                'timeZone': 'Asia/Kolkata'
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'Asia/Kolkata'
            },
            'attendees': [
                {'email': candidate_email, 'responseStatus': 'needsAction'}
            ],
            'conferenceData': {
                'createRequest': {
                    'requestId': f'interview_{candidate_name}_{datetime.now().timestamp()}',
                    'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                }
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},  # 1 day before
                    {'method': 'popup', 'minutes': 30}        # 30 min before
                ]
            }
        }
        
        event = calendar_service.events().insert(
            calendarId='primary',
            body=event,
            conferenceDataVersion=1
        ).execute()
        
        st.success(f"✅ Interview scheduled for {candidate_name}!")
        st.info(f"📅 Event ID: {event['id']}")
        if 'conferenceData' in event:
            st.info(f"📹 Meeting Link: {event['conferenceData']['entryPoints'][0]['uri']}")
        return event['id']
    
    except Exception as e:
        st.error(f"❌ Error scheduling interview: {str(e)}")
        return None

# ============================================================================
# GEMINI INITIALIZATION
# ============================================================================

def initialize_gemini():
    """Connects to Google Gemini API"""
    if not API_KEY:
        st.error("❌ API Key not found! Add GOOGLE_API_KEY to .env file")
        st.stop()
    
    genai.configure(api_key=API_KEY)
    return genai.GenerativeModel('gemini-2.0-flash')

# ============================================================================
# CORE AGENT LOGIC
# ============================================================================

def create_scoring_prompt(job_description, resumes_text):
    """Creates a prompt for Gemini to analyze and score resumes"""
    prompt = f"""You are an expert HR recruiter. Analyze these resumes against the job description.

JOB DESCRIPTION:
{job_description}

RESUMES:
{resumes_text}

For each resume, provide a JSON response with:
1. candidate_name: Full name
2. candidate_email: Email address (if found, else "not_provided")
3. match_score: 0-100 percentage
4. matched_skills: List of skills that match job description
5. missing_skills: List of skills required but missing
6. experience_fit: Brief assessment
7. recommendation: "Strong Match" / "Good Match" / "Weak Match"
8. reasoning: 2-3 sentence explanation
9. years_of_experience: Years of experience (numeric)

Return ONLY valid JSON array, no other text."""

    return prompt

def score_resumes(job_description, resumes_dict):
    """Main Agent Function - AI analyzes resumes"""
    model = initialize_gemini()
    
    # Format resumes for the AI
    resumes_text = "\n---\n".join([
        f"RESUME {i+1} - {name}:\n{content}"
        for i, (name, content) in enumerate(resumes_dict.items())
    ])
    
    # Create the analysis prompt
    prompt = create_scoring_prompt(job_description, resumes_text)
    
    try:
        # Send to Gemini AI
        response = model.generate_content(prompt)
        response_text = response.text
        
        # Parse the JSON response
        try:
            start = response_text.find('[')
            end = response_text.rfind(']') + 1
            json_str = response_text[start:end]
            results = json.loads(json_str)
        except:
            results = [{"error": "Failed to parse AI response"}]
        
        # Sort by match score (highest first)
        results_sorted = sorted(results, key=lambda x: x.get('match_score', 0), reverse=True)
        return results_sorted
    
    except Exception as e:
        st.error(f"❌ Error calling Gemini API: {str(e)}")
        return []

# ============================================================================
# DATA PROCESSING
# ============================================================================

def format_results_for_display(results):
    """Converts AI results into a nice table format"""
    if not results:
        return []
    
    formatted = []
    for rank, result in enumerate(results, 1):
        formatted.append({
            'Rank': rank,
            'Candidate': result.get('candidate_name', 'Unknown'),
            'Email': result.get('candidate_email', 'N/A'),
            'Match %': result.get('match_score', 0),
            'Status': result.get('recommendation', 'Unknown'),
            'Matched Skills': ', '.join(result.get('matched_skills', [])),
            'Missing Skills': ', '.join(result.get('missing_skills', [])),
            'Experience': result.get('years_of_experience', 'N/A'),
            'Reasoning': result.get('reasoning', 'N/A')
        })
    
    return formatted

# ============================================================================
# STREAMLIT UI
# ============================================================================

def main():
    """Main Streamlit app with File Upload"""
    st.set_page_config(
        page_title="Resume Screening Agent",
        page_icon="📄",
        layout="wide"
    )
    
    st.title("🤖 AI Resume Screening Agent")
    st.markdown("*Powered by Google Gemini, LangChain & File Processing*")
    
    # Initialize Firebase
    db = initialize_firebase()
    storage_bucket = None
    try:
        if db:
            storage_bucket = storage.bucket()
    except:
        storage_bucket = None
    
    # Initialize Google Calendar
    calendar_service = initialize_google_calendar()
    
    # Sidebar
    with st.sidebar:
        st.header("📋 Instructions")
        st.markdown("""
        1. **Company Info** - Name & details
        2. **Job Description** - What you're hiring for
        3. **Upload Resumes** - PDF, DOCX, or TXT files
        4. **Score & Analyze** - AI ranks candidates
        5. **View Results** - Download as CSV
        
        ⏱️ Takes 10-30 seconds per resume
        """)
        
        st.divider()
        st.markdown("**Supported File Formats:**")
        st.markdown("- 📄 PDF (.pdf)")
        st.markdown("- 📝 Word (.docx)")
        st.markdown("- 📋 Text (.txt)")
        
        st.divider()
        st.markdown("**Tech Stack:**")
        st.markdown("- 🤖 AI: Google Gemini 2.0")
        st.markdown("- 📖 PDF: PyPDF2")
        st.markdown("- 📄 Word: python-docx")
        st.markdown("- 🎨 UI: Streamlit")
    
    st.markdown("---")
    
    # Section 1: Company & Job Info
    st.subheader("🏢 Step 1: Company & Job Details")
    
    col1, col2 = st.columns(2)
    with col1:
        company_name = st.text_input("Company Name:", placeholder="e.g., Tech Corp")
    with col2:
        job_title = st.text_input("Job Title:", placeholder="e.g., Senior Developer")
    
    hiring_manager_email = st.text_input("Hiring Manager Email:", placeholder="manager@company.com")
    
    st.markdown("---")
    
    # Section 2: Job Description
    st.subheader("📝 Step 2: Enter Job Description")
    job_description = st.text_area(
        "Paste the job description here:",
        height=150,
        placeholder="e.g., Senior Python Developer with 5+ years experience..."
    )
    
    st.markdown("---")
    
    # Section 3: File Upload
    st.subheader("📤 Step 3: Upload Resumes (PDF/DOCX/TXT)")
    
    uploaded_files = st.file_uploader(
        "Upload resume files:",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=True,
        help="You can upload multiple resume files at once"
    )
    
    st.markdown("---")
    
    # Section 4: Action Button
    col1, col2, col3 = st.columns(3)
    
    with col2:
        score_button = st.button(
            "🚀 Score & Rank Resumes",
            use_container_width=True,
            type="primary"
        )
    
    # Section 5: Process and Display Results
    if score_button:
        # Validation
        if not job_description.strip():
            st.error("❌ Please enter a job description")
            return
        
        if not uploaded_files:
            st.error("❌ Please upload at least one resume file")
            return
        
        if not company_name or not hiring_manager_email:
            st.warning("⚠️ Company name and email are optional but recommended")
        
        # Process uploaded files
        with st.spinner("📖 Extracting text from resumes..."):
            resumes = {}
            for uploaded_file in uploaded_files:
                resume_text = process_resume_file(uploaded_file)
                if resume_text:
                    # Get candidate name from filename or extracted text
                    filename = uploaded_file.name.split('.')[0]
                    resumes[filename] = resume_text
                    st.success(f"✅ Processed: {uploaded_file.name}")
        
        if not resumes:
            st.error("❌ Failed to extract text from uploaded files")
            return
        
        # Score resumes
        with st.spinner("🤔 AI is analyzing resumes..."):
            results = score_resumes(job_description, resumes)
        
        if results and 'error' not in results[0]:
            st.success("✅ Screening complete!")
            st.markdown("---")
            
            # Display Results
            st.subheader("📊 Top Candidates")
            
            if len(results) > 0:
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric(
                        "🥇 Top Match",
                        results[0]['candidate_name'],
                        f"{results[0]['match_score']}%"
                    )
                with col2:
                    st.metric(
                        "📨 Email",
                        results[0].get('candidate_email', 'N/A')
                    )
                with col3:
                    st.metric(
                        "💼 Status",
                        results[0]['recommendation']
                    )
            
            # Detailed Rankings
            st.subheader("📋 Detailed Rankings")
            formatted_results = format_results_for_display(results)
            
            for rank, result in enumerate(formatted_results, 1):
                with st.expander(
                    f"Rank {rank}: {result['Candidate']} - {result['Match %']}% Match"
                ):
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown(f"**Email:** {result['Email']}")
                        st.markdown(f"**Status:** {result['Status']}")
                        st.markdown(f"**Match Score:** {result['Match %']}%")
                        st.markdown(f"**Experience:** {result['Experience']} years")
                    
                    with col2:
                        st.markdown(f"**Matched Skills:** {result['Matched Skills']}")
                        st.markdown(f"**Missing Skills:** {result['Missing Skills']}")
                        st.markdown(f"**Reasoning:** {result['Reasoning']}")
            
            # Download Results
            st.divider()
            st.subheader("📥 Download Results")
            
            import csv
            import io
            
            csv_buffer = io.StringIO()
            writer = csv.DictWriter(csv_buffer, fieldnames=formatted_results[0].keys())
            writer.writeheader()
            writer.writerows(formatted_results)
            
            st.download_button(
                label="Download as CSV",
                data=csv_buffer.getvalue(),
                file_name=f"screening_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
            
            # Firebase Storage Info
            st.divider()
            st.subheader("💾 Data Storage")
            if db:
                st.success("✅ Firebase Connected - Results can be saved")
            else:
                st.info("ℹ️ Results downloaded as CSV")
        
        else:
            st.error("❌ Failed to process resumes. Please try again.")


if __name__ == "__main__":
    main()