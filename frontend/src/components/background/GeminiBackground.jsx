export default function GeminiBackground() {
  return (
    <div className="fixed inset-0 w-full h-full -z-10 overflow-hidden bg-[#0d0f18] pointer-events-none">
      {/* Top subtle ambient purple/indigo aura */}
      <div className="absolute -top-[20%] left-1/2 -translate-x-1/2 w-[70vw] h-[50vw] max-w-[900px] max-h-[600px] bg-gradient-to-b from-purple-600/12 via-indigo-600/8 to-transparent rounded-full blur-3xl" />

      {/* Bottom right subtle cyan/blue aura */}
      <div className="absolute -bottom-[10%] -right-[5%] w-[45vw] h-[45vw] max-w-[600px] max-h-[600px] bg-blue-600/6 rounded-full blur-3xl" />

      {/* Center ambient glow */}
      <div className="absolute top-1/3 left-1/4 w-[35vw] h-[35vw] max-w-[500px] max-h-[500px] bg-purple-900/10 rounded-full blur-[120px]" />

      {/* Very faint subtle grid pattern overlay for modern texture */}
      <div
        className="absolute inset-0 opacity-[0.025]"
        style={{
          backgroundImage: `radial-gradient(rgba(255, 255, 255, 0.4) 1px, transparent 1px)`,
          backgroundSize: '32px 32px',
        }}
      />
    </div>
  );
}
