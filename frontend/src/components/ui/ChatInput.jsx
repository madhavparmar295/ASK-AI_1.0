import { useState, useRef, useEffect } from 'react';

export default function ChatInput({ onSend, onFileUpload, disabled = false, inputValue = '', setInputValue }) {
  const [localInput, setLocalInput] = useState('');
  const [isListening, setIsListening] = useState(false);
  const fileInputRef = useRef(null);
  const recognitionRef = useRef(null);

  // Sync external controlled state if provided
  const currentText = setInputValue ? inputValue : localInput;
  const updateText = setInputValue ? setInputValue : setLocalInput;

  // Initialize Web Speech API if supported
  useEffect(() => {
    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      const recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.lang = 'en-US';

      recognition.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        updateText((prev) => (prev ? `${prev} ${transcript}` : transcript));
        setIsListening(false);
      };

      recognition.onerror = () => {
        setIsListening(false);
      };

      recognition.onend = () => {
        setIsListening(false);
      };

      recognitionRef.current = recognition;
    }
  }, [updateText]);

  const handleSubmit = (e) => {
    e?.preventDefault();
    if (currentText.trim() && !disabled) {
      onSend?.(currentText.trim());
      updateText('');
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleAttachClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileSelected = (e) => {
    const file = e.target.files?.[0];
    if (file) {
      onFileUpload?.(file);
      e.target.value = '';
    }
  };

  const toggleVoice = () => {
    if (!recognitionRef.current) {
      alert('Voice dictation is not supported by your current browser.');
      return;
    }
    if (isListening) {
      recognitionRef.current.stop();
      setIsListening(false);
    } else {
      try {
        recognitionRef.current.start();
        setIsListening(true);
      } catch (err) {
        console.error('Speech recognition error:', err);
      }
    }
  };

  return (
    <div className="input-section">
      {/* Hidden file input */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileSelected}
        className="hidden"
        accept=".pdf,.docx,.doc,.txt,.csv,.xlsx,.xls,.png,.jpg,.jpeg"
      />

      <form onSubmit={handleSubmit} className="w-full">
        <div className="capsule-box">
          {/* Attach Button */}
          <button
            type="button"
            className="icon-btn"
            title="Attach file"
            onClick={handleAttachClick}
            disabled={disabled}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
            </svg>
          </button>

          {/* Text Input */}
          <input
            type="text"
            className="main-input"
            id="mainInput"
            value={currentText}
            onChange={(e) => updateText(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            placeholder={
              disabled
                ? 'Synthesizing response...'
                : 'Ask questions about your emails, documents, or data...'
            }
          />

          {/* Voice Dictation Button */}
          <button
            type="button"
            className={`icon-btn ${isListening ? 'text-red-400' : ''}`}
            title={isListening ? 'Listening...' : 'Voice dictation'}
            onClick={toggleVoice}
            disabled={disabled}
            style={isListening ? { color: '#ff4d4f' } : undefined}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              <line x1="12" y1="19" x2="12" y2="23" />
              <line x1="8" y1="23" x2="16" y2="23" />
            </svg>
          </button>

          {/* Send Button */}
          <button
            type="submit"
            className="btn-send"
            id="btnSend"
            title="Send query"
            disabled={!currentText.trim() || disabled}
            style={{
              opacity: !currentText.trim() || disabled ? 0.6 : 1,
              cursor: !currentText.trim() || disabled ? 'not-allowed' : 'pointer',
            }}
          >
            <svg viewBox="0 0 24 24">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
      </form>

      <div className="disclaimer-text">
        Ask AI answers questions based on your indexed emails and uploaded files.
      </div>
    </div>
  );
}
