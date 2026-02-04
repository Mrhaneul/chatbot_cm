# 🚀 Backend Integration Guide

This guide shows how to connect your React UI to the FastAPI backend.

## 📁 Files Created

1. **`src/services/api.ts`** - API service layer for backend communication
2. **`src/App-integrated.tsx`** - Updated App component with real backend integration
3. **`src/components/ChatInput-updated.tsx`** - ChatInput with loading state support
4. **`src/components/ChatHeader-updated.tsx`** - ChatHeader with API status indicator
5. **`.env.example`** - Environment variables template

## 🔧 Setup Steps

### Step 1: Copy the New Files

```bash
# Navigate to your UI project directory
cd /path/to/Campus_Store_Assistant_Chatbot_UI

# Create services directory
mkdir -p src/services

# Copy the API service
cp src/services/api.ts src/services/api.ts

# Replace the old files with updated versions
cp src/App-integrated.tsx src/App.tsx
cp src/components/ChatInput-updated.tsx src/components/ChatInput.tsx
cp src/components/ChatHeader-updated.tsx src/components/ChatHeader.tsx

# Copy environment template
cp .env.example .env
```

### Step 2: Install Dependencies (if needed)

The project already has all required dependencies. No additional packages needed!

### Step 3: Configure Environment Variables

Create a `.env` file in the project root:

```bash
# .env
VITE_API_URL=http://localhost:8000
```

### Step 4: Start the Backend

In your backend directory:

```bash
cd /path/to/chatbot_cm
conda activate campus-store-bot
uvicorn app.main:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
✓ Loaded Cengage-specific instruction index
✓ Loaded McGraw Hill-specific instruction index
✓ Loaded SimuCase-specific instruction index
# ... etc
```

### Step 5: Start the Frontend

In your UI directory:

```bash
npm run dev
```

You should see:
```
  VITE v6.3.5  ready in 500 ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
```

### Step 6: Test the Integration

1. **Open** http://localhost:5173 in your browser
2. **Check** the header - should show "Connected" with a green WiFi icon
3. **Type** a test message: "I need access to McGraw Hill Connect"
4. **Verify** you get a real response from the backend

## 🎯 Key Features Added

### ✅ Real Backend Connection
- Sends messages to FastAPI `/chat` endpoint
- Receives responses with confidence scores and sources
- Maintains session state across conversation

### ✅ API Status Monitoring
- Green "Connected" indicator when backend is available
- Red "Offline" indicator if backend is down
- Helpful error messages for connection issues

### ✅ Loading States
- Animated "Lance is thinking..." indicator
- Disabled input during processing
- Auto-scroll to new messages

### ✅ Session Management
- Unique session ID generated per browser session
- Persistent conversation history
- Session cleared on page refresh

### ✅ Smart PDF Recommendations
- Dynamically updates based on detected platform
- Shows relevant guides (Cengage, McGraw Hill, Pearson, etc.)
- Includes general troubleshooting tips

## 🧪 Testing Checklist

### Test 1: Basic Connection
```
User: "Hello"
Expected: Bot responds with greeting
```

### Test 2: Platform Detection
```
User: "I need help with Cengage"
Expected: Bot asks "textbook or MindTap?"
```

### Test 3: Specific Platform
```
User: "I need access to McGraw Hill Connect"
Expected: Step-by-step Connect instructions
```

### Test 4: SimuCase (Case Sensitivity)
```
User: "I need access to simucase"
Expected: 15-step SimuCase instructions
```

### Test 5: Error Handling
```
1. Stop the backend (Ctrl+C)
2. Send a message
Expected: Red "Offline" indicator + error message
```

## 🔍 Debugging

### If UI shows "Offline"

1. **Check backend is running:**
   ```bash
   curl http://localhost:8000/sessions/stats
   ```
   Should return JSON with session data

2. **Check CORS (if needed):**
   If you see CORS errors, add this to `main.py`:
   ```python
   from fastapi.middleware.cors import CORSMiddleware

   app.add_middleware(
       CORSMiddleware,
       allow_origins=["http://localhost:5173"],
       allow_credentials=True,
       allow_methods=["*"],
       allow_headers=["*"],
   )
   ```

3. **Check ports:**
   - Backend: `http://localhost:8000`
   - Frontend: `http://localhost:5173`

### If messages don't appear

1. **Open browser console** (F12)
2. **Look for errors** in the Console tab
3. **Check Network tab** for failed API calls

### View API Responses

Add this to see what the backend returns:

```typescript
// In App-integrated.tsx, line 72
console.log('API Response:', response);
```

## 📊 Message Flow

```
User types message
    ↓
Frontend sends to /chat endpoint
    ↓
Backend processes with RAG
    ↓
Backend returns:
  - reply (bot response)
  - source (document ID)
  - confidence (0.0-1.0)
  - article_link (optional)
    ↓
Frontend displays response
    ↓
PDF recommendations updated
```

## 🎨 Customization

### Change API URL

In `.env`:
```bash
VITE_API_URL=https://your-backend-url.com
```

### Adjust Typing Speed

In `App-integrated.tsx`, modify the loading delay:

```typescript
// Current: immediate display
// To add delay:
setTimeout(() => {
  setMessages(prev => [...prev, assistantMessage]);
}, 1000); // 1 second delay
```

### Customize Error Messages

In `App-integrated.tsx`, line 91:

```typescript
content: 'Your custom error message here'
```

## 🚨 Common Issues

### Issue: "Network error" in console
**Solution:** Make sure backend is running on port 8000

### Issue: CORS errors
**Solution:** Add CORS middleware to FastAPI (see debugging section)

### Issue: Session not persisting
**Solution:** Session ID is stored in component state and resets on refresh. This is expected behavior.

### Issue: Slow responses
**Solution:** Check backend logs for LLM generation time. Normal is 15-30 seconds.

## 📝 Next Steps

1. ✅ Test all platform queries (Cengage, McGraw Hill, Pearson, SimuCase, etc.)
2. ✅ Verify PDF recommendations appear correctly
3. ✅ Test multi-turn conversations (clarification flows)
4. 🔜 Add file upload functionality (if needed)
5. 🔜 Add chat history export (if needed)
6. 🔜 Deploy to production

## 🎉 You're Done!

Your UI is now fully integrated with the FastAPI backend. The chatbot should be responding with real RAG-powered answers!

For issues or questions, check the browser console and backend logs.
