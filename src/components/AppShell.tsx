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
        <div className="mx-auto flex h-20 max-w-7xl items-center justify-center px-6 lg:px-10">
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
        </div>
      </header>
      {children}
    </div>
  );
}
