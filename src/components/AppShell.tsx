"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navItems = [
  { href: "/upload", label: "Upload", match: ["/upload", "/preload"] },
  { href: "/exams", label: "Processamentos", match: ["/exams"] },
  { href: "/exams", label: "Resultados", match: ["/results"] },
];

export default function AppShell({
  children,
  active,
}: {
  children: React.ReactNode;
  active?: "upload" | "processamentos" | "resultados";
}) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen bg-[#f8fbff] text-[#07122f]">
      <header className="sticky top-0 z-30 border-b border-[#dce5f2] bg-white/95 backdrop-blur">
        <div className="mx-auto grid h-20 max-w-7xl grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-6 px-6 lg:px-10">
          <Link href="/" className="text-3xl font-bold tracking-[-0.02em] text-[#0b66f6]">
            ExamCrew
          </Link>
          <nav className="flex h-full items-center justify-center gap-8 text-sm font-medium text-[#53617f] sm:gap-14">
            {navItems.map((item) => {
              const isActive = active
                ? item.label.toLowerCase() === active
                : item.match.some((prefix) => pathname.startsWith(prefix));
              return (
                <Link
                  key={item.label}
                  href={item.href}
                  className={`relative flex h-full items-center transition-colors ${
                    isActive ? "text-[#0b66f6]" : "hover:text-[#07122f]"
                  }`}
                >
                  {item.label}
                  {isActive && (
                    <span className="absolute inset-x-0 bottom-0 h-0.5 rounded-full bg-[#0b66f6]" />
                  )}
                </Link>
              );
            })}
          </nav>
          <div className="hidden items-center gap-5 md:flex">
            <button
              type="button"
              className="flex h-11 w-11 items-center justify-center rounded-full text-[#07122f] transition hover:bg-[#eaf2ff] hover:text-[#0b66f6]"
              aria-label="Tema"
            >
              <svg className="h-7 w-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
              </svg>
            </button>
            <div className="h-10 w-px bg-[#dce5f2]" />
            <button
              type="button"
              className="flex items-center gap-3 rounded-full text-[#07122f]"
              aria-label="Conta"
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-full bg-[#0b66f6] text-sm font-bold text-white shadow-[0_12px_30px_rgba(11,102,246,0.24)]">
                EC
              </span>
              <svg className="h-5 w-5 text-[#07122f]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="m6 9 6 6 6-6" />
              </svg>
            </button>
          </div>
        </div>
      </header>
      {children}
    </div>
  );
}
