# Ask AI Frontend

<div align="center">

A premium, open-source AI chatbot frontend featuring a stunning dark mode UI with subtle purple dither background and glassmorphism effects.

[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](https://opensource.org/licenses/MIT)
[![React](https://img.shields.io/badge/React-19-blue)](https://react.dev/)
[![Vite](https://img.shields.io/badge/Vite-8.1-green)](https://vite.dev/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind-4.3-38bdf8)](https://tailwindcss.com/)

![Ask AI Frontend Preview](https://via.placeholder.com/800x400/1a0530/7c3aed?text=Premium+AI+Chatbot+UI)

</div>

## ✨ Features

- 🎨 **Premium Dark Mode** - Eye-catching design with purple accent colors
- 🌊 **Animated Dither Background** - Subtle, interactive canvas-based background effect
- 🪟 **Glassmorphism UI** - Modern frosted glass effects throughout
- 📱 **Fully Responsive** - Desktop sidebar transforms to mobile bottom navigation
- 🔊 **Voice Input Ready** - Microphone integration for voice messages
- 📎 **File Attachments** - File upload UI (demo mode)
- 💬 **Smart Chat Interface** - Greeting screen with action buttons
- ⚡ **Demo Mode** - Fully functional with mock responses
- 🔌 **API Ready** - Structured endpoints for Django/FastAPI backend
- ♿ **Accessible** - ARIA labels and keyboard navigation support

## 🚀 Quick Start

### Prerequisites

- Node.js 18+ and npm/yarn/pnpm

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/ask-ai-frontend.git
cd ask-ai-frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) to see the application.

### Build for Production

```bash
npm run build
npm run preview
```

## 📁 Project Structure

```
ask-ai-frontend/
├── public/                    # Static assets
├── src/
│   ├── components/
│   │   ├── background/
│   │   │   └── DitherBackground.jsx    # Animated background
│   │   ├── layout/
│   │   │   ├── Sidebar.jsx             # Navigation sidebar
│   │   │   └── MainContent.jsx         # Main content area
│   │   ├── ui/
│   │   │   ├── ActionButton.jsx        # Glassmorphism action cards
│   │   │   └── ChatInput.jsx            # Message input with attachments
│   │   └── icons/
│   │       └── IconSet.jsx             # Reusable icon components
│   ├── services/
│   │   ├── api.js                       # API endpoint configuration
│   │   └── demoService.js               # Demo mode handlers
│   ├── styles/
│   │   └── globals.css                  # Global styles & Tailwind
│   ├── App.jsx                          # Root component
│   └── main.jsx                         # Entry point
├── index.html
├── package.json
├── vite.config.js
├── tailwind.config.js
└── README.md
```

## 🎨 Customization

### Colors

Edit `tailwind.config.js` to customize the color palette:

```javascript
theme: {
  extend: {
    colors: {
      purple: {
        600: '#7c3aed',  // Primary purple
        // ... other shades
      },
    },
  },
}
```

### Background Animation

Adjust the dither background in `src/components/background/DitherBackground.jsx`:

```javascript
<Dither
  waveColor={[0.35, 0.14, 0.72]}  // RGB values 0-1
  waveSpeed={0.05}
  opacity={0.35}
  enableMouseInteraction={true}
/>
```

### API Configuration

Set your backend URL in `src/services/api.js`:

```javascript
export const API_CONFIG = {
  BASE_URL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api',
  DEMO_MODE: false,  // Set to false to use real API
};
```

Or use environment variables:

```bash
# .env file
VITE_API_BASE_URL=http://your-backend.com/api
```

## 🔌 Backend Integration

This frontend is ready to connect to Django or FastAPI backends. The API structure is defined in `src/services/api.js`:

### Endpoints

- `POST /api/chat/send` - Send message to AI
- `POST /api/chat/upload` - Upload file attachment
- `POST /api/chat/voice` - Submit voice input
- `GET /api/chat/history` - Get chat history
- `DELETE /api/chat/messages/:id` - Delete message

### Response Format

```javascript
{
  "success": true,
  "data": {
    "message": "AI response text",
    "timestamp": "2026-07-07T10:00:00Z",
    "id": "msg-123"
  }
}
```

## 🛠️ Tech Stack

- **Framework**: React 19 with Vite 8
- **Styling**: Tailwind CSS 4
- **Icons**: Lucide React
- **3D Graphics**: Three.js + React Three Fiber
- **Effects**: Postprocessing (for dither effect)
- **Build Tool**: Vite

## 🌐 Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Mobile browsers (iOS Safari, Chrome Mobile)

## 📱 Responsive Design

- **Desktop** (>1024px): Full sidebar with hover expansion
- **Tablet** (768-1024px): Collapsible sidebar
- **Mobile** (<768px): Bottom navigation bar

## ♿ Accessibility

- ARIA labels on all interactive elements
- Keyboard navigation support
- Reduced motion preference support
- High contrast mode compatible
- Screen reader friendly

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Quick Contribution Guide

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Dither Background**: Inspired by [reactbits.dev](https://reactbits.dev/)
- **Icons**: [Lucide Icons](https://lucide.dev/)
- **Glassmorphism**: Modern UI design pattern
- **Three.js**: Amazing 3D library for the web

## 📧 Contact

For questions or support:
- Open an issue on GitHub
- Email: your@email.com
- Twitter: [@yourhandle](https://twitter.com/yourhandle)

---

<div align="center">

**Built with ❤️ for the open-source community**

[⭐ Star this repo](https://github.com/yourusername/ask-ai-frontend) - it helps!

</div>
