# Audit Report Stamping

**Audit Report Stamping** is an automated internal web application designed for HR to batch-sign and batch-stamp 120–140 statutory compliance and audit files every month in minutes instead of doing it manually line-by-line.

---

## Key Features

1. **Massive Batch Upload (120–140+ Files)**:
   - Supports **PDF (`.pdf`)**, **Word (`.docx`)**, and **Excel (`.xlsx`, `.xls`)** audit files simultaneously.
   - Drag & drop multiple files or entire folders with real-time file count, format tags, and size stats.

2. **Excel Report Preview & Precision Stamping**:
   - Preview spreadsheet registers (e.g. Form-T Muster Roll, Form-F Wage Register, Equal Remuneration).
   - Shows the exact print layout with rows and columns so you can see the designated signature & seal spots.
   - Drag & drop the CTO Signature and Company Seal directly onto the Excel sheet spot.
   - Automatically converts Excel files into clean, signed & stamped audit PDFs.

3. **Smart Hybrid Stamping Intelligence**:
   - **Auto-Detection Mode (Recommended)**: Automatically searches each document for signatory lines (e.g., `CTO`, `Chief Technology Officer`, `Authorized Signatory`, `Authorised Signatory`, `Signature of Employer`, `Director`).
   - Automatically aligns the CTO Signature directly above the detected signatory line and positions the Company Seal beside it.
   - **Visual Fallback**: If a scanned or non-standard document doesn't contain matching text, it seamlessly falls back to the exact page and coordinates configured in the visual preview.

3. **Interactive Document Preview**:
   - Switch between any document in the batch and any page to preview placement.
   - Draggable & resizable CTO Signature and Company Seal boxes with percentage sliders.
   - "Test Auto-Detect on this Page" button to visually verify where keywords match.

4. **Real-Time Asynchronous Processing**:
   - Non-blocking background worker processes 140 files with a live progress bar (`45 / 138 files (33%)`).
   - Live activity log displaying per-document status and detected keyword locations.

5. **One-Click Instant Download**:
   - **Download All as ZIP (Originals)**: Keeps original PDF and Word formats.
   - **Download All as PDF (ZIP)**: Automatically converts Word `.docx` documents into high-quality `.pdf` format using Microsoft Word automation.

6. **CTO Signature & Seal Management**:
   - Upload official CTO Signature and Company Seal once; they are saved permanently for all future monthly batches.
   - Built-in transparency tool to eliminate white backgrounds from photos or scans of signatures and stamps.

7. **Date Replacement (Optional)**:
   - Option to update document dates (e.g. `05 July 2026`) across the batch.

---

## Quick Start Guide

### 1. Launch the Application
Double-click `run.bat` in the project folder (or run it from a terminal):

```cmd
run.bat
```

The application runs on `http://localhost:8000` (or `http://YOUR-LAN-IP:8000` from any computer on the office network).

### 2. Log In
Open `http://localhost:8000` in any web browser:
- **Default HR Account**: `hr` / `hr123`
- **Demo Account**: `demo` / `demo123`

To create or reset passwords at any time:
```cmd
venv\Scripts\python create_user.py <username> <password>
```

### 3. Monthly Workflow for HR
1. **Upload CTO Signature & Stamp** *(first time only, or when updating assets)*:
   - Go to **CTO Signature & Stamp** in the top navigation bar.
   - Upload the signature image and company seal image. Both images are already loaded with Claaps assets.
2. **Start a New Batch**:
   - Go to **New Batch**.
   - Drag and drop your 120–140 monthly audit files into the upload box.
   - Click **Continue to Placement**.
3. **Review Placement Rules**:
   - Confirm **Smart Keyword Auto-Detect** is selected.
   - Use the interactive preview to check any sample file and test keyword detection.
   - Ensure **Auto-convert Word (.docx) to PDF** is checked if you want complete PDF submission files.
4. **Process All Files**:
   - Click **Process All Files**.
   - Watch the live progress bar as each file is stamped.
5. **Download**:
   - Click **Download All as PDF (ZIP)** or **Download All as ZIP** to retrieve all completed files in a single archive.
