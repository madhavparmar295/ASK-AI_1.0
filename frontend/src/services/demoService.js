/**
 * Demo Service - Mock Responses for Frontend Development
 *
 * This service simulates backend responses when in demo mode.
 * Replace these with real API calls when backend is ready.
 */

// Demo responses for different message types
const demoResponses = {
  greeting: [
    "Hello! I'm Ask AI, your personal assistant. How can I help you today?",
    "Hi there! I'm ready to assist you with any questions or tasks.",
    "Hey! I'm here to help. What would you like to know?",
  ],
  quantum: [
    "Quantum computing is like having a super-powered calculator that can explore many possibilities at once! While regular computers use bits (0s and 1s), quantum computers use 'qubits' that can be both 0 and 1 simultaneously. This allows them to solve certain complex problems much faster, like drug discovery, encryption, and optimization challenges.",
  ],
  coding: [
    "Here's a Python function to sort a list:\n\n```python\ndef sort_list(items):\n    return sorted(items)\n\n# Example usage\nmy_list = [3, 1, 4, 1, 5, 9]\nsorted_list = sort_list(my_list)\nprint(sorted_list)  # [1, 1, 3, 4, 5, 9]\n```\n\nThis uses Python's built-in `sorted()` function which implements an efficient Timsort algorithm.",
  ],
  productivity: [
    "Here are some innovative productivity app ideas:\n\n1. **FocusFlow** - An app that uses AI to block distractions only when you're struggling to concentrate\n2. **HabitStack** - Gamify habit building by unlocking new features as you maintain streaks\n3. **TimeSlice** - Auto-schedules breaks based on your actual fatigue levels (using device sensors)\n4. **TaskTunnel** - Turns task completion into an endless runner game where each task is an obstacle\n\nWould you like me to expand on any of these?",
  ],
  ai_news: [
    "Latest AI News Summary:\n\n🚀 **Breakthrough Models**: New open-source models are achieving performance comparable to closed-source alternatives\n📱 **Edge AI**: More AI capabilities are moving to devices for privacy and speed\n🤖 **AI Agents**: Autonomous agents that can complete multi-step tasks are becoming mainstream\n⚖️ **Regulation**: New AI safety guidelines are being proposed globally\n🔬 **Research**: Significant progress in areas like reasoning, multimodal understanding, and efficiency\n\nWant me to dive deeper into any of these topics?",
  ],
  default: [
    "That's an interesting question! I'd be happy to help you explore that topic further. Could you provide more details?",
    "I understand what you're asking. Let me think about the best way to approach this...",
    "Great question! Here's what I can tell you about that...",
    "I'm processing your request. In a full implementation, this would connect to your Django/FastAPI backend.",
  ],
};

/**
 * Simulate AI response for a message
 * @param {string} message - User's message
 * @returns {Promise<object>} Mock response with delay
 */
export async function getDemoResponse(message) {
  // Simulate network delay
  const delay = Math.random() * 1000 + 500; // 500-1500ms delay
  await new Promise((resolve) => setTimeout(resolve, delay));

  const lowerMessage = message.toLowerCase();

  // Determine response type based on message content
  let responses;
  if (lowerMessage.includes('deadline') || lowerMessage.includes('email') || lowerMessage.includes('inbox')) {
    responses = [
      `Here are your upcoming deadlines:\n\n` +
      `1. **Project Milestone 2**: Submission closes this Friday at 11:59 PM.\n` +
      `2. **Hostel Fee Clearance**: Clearance required before the 5th of this month.\n` +
      `3. **Course Feedback**: Portal is currently open for the term.`
    ];
  } else if (lowerMessage.includes('extract') || lowerMessage.includes('pdf') || lowerMessage.includes('document')) {
    responses = [
      `The uploaded document covers the system architecture, semantic retrieval pipeline, and vector indexing details.`
    ];
  } else if (lowerMessage.includes('receipt') || lowerMessage.includes('hostel') || lowerMessage.includes('grade')) {
    responses = [
      `Here are your records:\n\n` +
      `• **Hostel Fee Receipt**: Ref #HST-2026-8812 (Paid in full).\n` +
      `• **Room Allotment**: Block C, Room 314 confirmed for the current term.\n` +
      `• **Semester Grade Statement**: All core credits fulfilled.`
    ];
  } else if (lowerMessage.includes('draft') || lowerMessage.includes('follow-up') || lowerMessage.includes('inquiry')) {
    responses = [
      `Here is the email draft:\n\n` +
      `**Subject**: Follow-Up: Pending Inquiry Regarding Documentation & Next Steps\n\n` +
      `Dear Team,\n\n` +
      `I hope this email finds you well.\n\n` +
      `I am following up on our previous correspondence regarding the status of the submitted inquiry. Please let me know if any updates or further details are needed.\n\n` +
      `Thank you for your assistance.\n\n` +
      `Best regards,\nParth`
    ];
  } else if (lowerMessage.includes('hello') || lowerMessage.includes('hi') || lowerMessage.includes('hey')) {
    responses = demoResponses.greeting;
  } else if (lowerMessage.includes('quantum')) {
    responses = demoResponses.quantum;
  } else if (lowerMessage.includes('code') || lowerMessage.includes('python') || lowerMessage.includes('function')) {
    responses = demoResponses.coding;
  } else if (lowerMessage.includes('productivity') || lowerMessage.includes('app') || lowerMessage.includes('idea')) {
    responses = demoResponses.productivity;
  } else if (lowerMessage.includes('ai') || lowerMessage.includes('news') || lowerMessage.includes('latest')) {
    responses = demoResponses.ai_news;
  } else {
    responses = demoResponses.default;
  }

  // Pick a random response from the category
  const response = responses[Math.floor(Math.random() * responses.length)];

  return {
    success: true,
    data: {
      message: response,
      timestamp: new Date().toISOString(),
      id: `demo-${Date.now()}`,
    },
  };
}

/**
 * Simulate file upload
 * @param {File} file - File being "uploaded"
 */
export async function demoUploadFile(file) {
  const delay = Math.random() * 800 + 400; // 400-1200ms
  await new Promise((resolve) => setTimeout(resolve, delay));

  return {
    success: true,
    data: {
      filename: file.name,
      size: file.size,
      type: file.type,
      id: `file-${Date.now()}`,
    },
  };
}

/**
 * Simulate voice input processing
 * @returns {Promise<object>} Mock transcribed text
 */
export async function demoVoiceInput() {
  const delay = Math.random() * 1000 + 500;
  await new Promise((resolve) => setTimeout(resolve, delay));

  const demoVoiceTexts = [
    "Hello, can you help me with something?",
    "What's the weather like today?",
    "Tell me a joke",
    "How do I write a for loop in Python?",
  ];

  return {
    success: true,
    data: {
      text: demoVoiceTexts[Math.floor(Math.random() * demoVoiceTexts.length)],
      confidence: 0.95,
    },
  };
}

/**
 * Demo chat history
 */
export const demoChatHistory = [
  {
    id: '1',
    role: 'user',
    content: 'What is quantum computing?',
    timestamp: '2026-07-07T10:00:00Z',
  },
  {
    id: '2',
    role: 'assistant',
    content: demoResponses.quantum[0],
    timestamp: '2026-07-07T10:00:02Z',
  },
];

/**
 * Get demo chat history
 */
export async function getDemoHistory() {
  const delay = 300;
  await new Promise((resolve) => setTimeout(resolve, delay));

  return {
    success: true,
    data: demoChatHistory,
  };
}
