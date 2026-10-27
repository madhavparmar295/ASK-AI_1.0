# Contributing to Ask AI Frontend

Thank you for your interest in contributing to Ask AI Frontend! This document provides guidelines and instructions for contributing.

## 🤝 How to Contribute

### Reporting Issues

Before creating bug reports, please check existing issues to avoid duplicates. When creating an issue:

- Use a clear and descriptive title
- Provide detailed information about the problem
- Include steps to reproduce
- Add screenshots if applicable
- Specify your environment (OS, browser, Node version)

### Suggesting Features

We love feature suggestions! Please:

- Use the `feature-request` label
- Clearly describe the feature and its use case
- Provide examples of how it would work
- Consider if it fits the project's scope

## 🛠️ Development Setup

### Prerequisites

- Node.js 18 or higher
- npm, yarn, or pnpm
- Git

### Fork and Clone

```bash
# Fork the repository on GitHub
# Clone your fork
git clone https://github.com/YOUR_USERNAME/ask-ai-frontend.git
cd ask-ai-frontend

# Add upstream remote
git remote add upstream https://github.com/ORIGINAL_OWNER/ask-ai-frontend.git
```

### Install Dependencies

```bash
npm install
```

### Development

```bash
# Start dev server
npm run dev

# Run linter
npm run lint
```

## 📝 Coding Standards

### Code Style

We follow these conventions:

- **JavaScript**: Standard JS style (enforced by oxlint)
- **Components**: Functional components with hooks
- **Naming**: camelCase for variables/funcs, PascalCase for components
- **File Names**: PascalCase.jsx for components, lowercase.js for utilities

### Example Component

```jsx
import { useState } from 'react';
import { Icon } from 'lucide-react';

/**
 * Brief description of what the component does
 * @param {Object} props - Component props
 */
export default function MyComponent({ title, onAction }) {
  const [state, setState] = useState(null);

  const handleClick = () => {
    onAction?.(state);
  };

  return (
    <div className="glass rounded-lg p-4">
      <h3 className="text-white">{title}</h3>
      <button onClick={handleClick}>Action</button>
    </div>
  );
}
```

### Comments

- Use JSDoc comments for functions/components
- Add inline comments for complex logic
- Keep comments up-to-date with code changes

### Tailwind CSS

- Use existing custom colors from `tailwind.config.js`
- Prefer utility classes over custom CSS
- Create reusable component patterns
- Group related classes: `flex flex-col gap-4`

## 🧪 Testing

### Before Submitting

1. **Run dev server**: `npm run dev`
2. **Test manually**:
   - Check all interactive elements
   - Test responsive breakpoints (320px, 768px, 1024px, 1920px)
   - Verify accessibility (keyboard navigation, screen reader)
3. **Run linter**: `npm run lint`
4. **Test build**: `npm run build`

### Browser Testing

Test in these browsers:
- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)
- Mobile Safari (iOS 14+)
- Chrome Mobile (Android)

## 📂 Project Structure Guidelines

### Adding Components

Place components in appropriate directories:

```
src/components/
├── background/     # Background effects
├── layout/         # Layout components (Sidebar, MainContent)
├── ui/            # Reusable UI elements
└── icons/         # Icon wrappers/helpers
```

### Adding Services

API-related code goes in `src/services/`:

```
src/services/
├── api.js          # API endpoints and configuration
└── demoService.js  # Demo/mock handlers
```

## 🔄 Git Workflow

### Branch Naming

- `feature/` - New features (`feature/add-dark-mode`)
- `fix/` - Bug fixes (`fix/fix-mobile-nav`)
- `docs/` - Documentation (`docs/update-readme`)
- `refactor/` - Code refactoring (`refactor/optimize-components`)

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): description

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `perf`: Performance improvements
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

Examples:
```bash
git commit -m "feat(chat): add voice input support"
git commit -m "fix(sidebar): resolve mobile menu z-index"
git commit -m "docs(readme): update installation instructions"
```

### Pull Request Process

1. **Update your branch**:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Push to your fork**:
   ```bash
   git push origin feature/your-feature
   ```

3. **Create Pull Request** on GitHub

4. **PR Checklist**:
   - [ ] Code follows project style guidelines
   - [ ] Tested manually in multiple browsers
   - [ ] No linting errors
   - [ ] Updated documentation if needed
   - [ ] Added comments for complex logic
   - [ ] All commits are properly formatted

5. **Wait for review** - maintainers will review your PR

## 🎨 Design Guidelines

### Color Usage

- **Primary**: Purple (`purple-600` - #7c3aed)
- **Text**: White (`text-white`), Gray-400 (`text-gray-400`)
- **Background**: Glass effects (`bg-white/5` with `backdrop-blur`)

### Component Patterns

**Glassmorphism Card**:
```jsx
<div className="glass rounded-2xl p-6">
  {/* Content */}
</div>
```

**Glow Effect**:
```jsx
<div className="glow-purple">
  {/* Content */}
</div>
```

**Hover Animation**:
```jsx
<div className="transition-all hover:scale-105 active:scale-95">
  {/* Content */}
</div>
```

## 🐛 Debugging

### Common Issues

**Dev server won't start**:
```bash
# Clear cache and reinstall
rm -rf node_modules package-lock.json
npm install
```

**Styles not loading**:
- Check `globals.css` is imported in `main.jsx`
- Verify Tailwind config paths
- Clear browser cache

**Build errors**:
- Check all imports are correct
- Verify no circular dependencies
- Check for missing dependencies

## 💡 Tips for Good Contributions

1. **Keep it small** - Smaller PRs are easier to review
2. **Write clear descriptions** - Explain what and why
3. **Test thoroughly** - Check multiple scenarios
4. **Follow patterns** - Match existing code style
5. **Communicate** - Ask questions if unsure
6. **Be patient** - Reviewers volunteer their time

## 📜 Code of Conduct

### Our Pledge

We strive to:
- Be inclusive and welcoming
- Be respectful and constructive
- Focus on what is best for the community
- Show empathy towards other community members

### Unacceptable Behavior

- Harassment or discrimination
- Personal attacks
- Public or private harassment
- Publishing others' private information
- Anything unprofessional or inappropriate

## 🎯 Priority Areas

We're currently looking for help with:

1. **Accessibility** - Improve ARIA labels and keyboard nav
2. **Performance** - Optimize animations and rendering
3. **Mobile Experience** - Enhance touch interactions
4. **Testing** - Add unit and integration tests
5. **Documentation** - Improve code comments and guides
6. **Internationalization** - Add i18n support

## ❓ Questions?

- Open an issue with the `question` label
- Join our community chat (link coming soon)
- Check existing issues and discussions

---

**Thank you for contributing to Ask AI Frontend!** 🎉

Every contribution, no matter how small, helps make this project better for everyone.
