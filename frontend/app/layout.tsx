"use client";
import "./globals.css";
import { Inter } from "next/font/google";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "react-hot-toast";
import { useState } from "react";
import {
  Package, Users, ShoppingCart, Globe, BarChart2, Menu, X
} from "lucide-react";
import clsx from "clsx";

const inter = Inter({ subsets: ["latin"] });

const NAV = [
  { href: "/", label: "Dashboard", icon: BarChart2 },
  { href: "/products", label: "Products", icon: Package },
  { href: "/suppliers", label: "Suppliers", icon: Users },
  { href: "/orders", label: "Orders", icon: ShoppingCart },
  { href: "/marketplace", label: "Marketplace", icon: Globe },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient());
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const pathname = usePathname();

  return (
    <html lang="en">
      <head><title>Maga — Fulfillment Platform</title></head>
      <body className={`${inter.className} bg-gray-50 text-gray-900`}>
        <QueryClientProvider client={client}>
          <Toaster position="top-right" />
          <div className="flex h-screen overflow-hidden">
            {/* Sidebar */}
            <aside className={clsx(
              "fixed inset-y-0 left-0 z-50 w-60 bg-white border-r border-gray-200 flex flex-col transition-transform lg:translate-x-0 lg:static lg:inset-auto",
              sidebarOpen ? "translate-x-0" : "-translate-x-full"
            )}>
              <div className="flex items-center gap-2 px-5 py-4 border-b border-gray-100">
                <span className="text-xl font-bold text-blue-600">Maga</span>
                <span className="text-xs text-gray-400 mt-1">Fulfillment</span>
              </div>
              <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
                {NAV.map(({ href, label, icon: Icon }) => (
                  <Link
                    key={href}
                    href={href}
                    onClick={() => setSidebarOpen(false)}
                    className={clsx(
                      "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                      pathname === href || (href !== "/" && pathname.startsWith(href))
                        ? "bg-blue-50 text-blue-700"
                        : "text-gray-600 hover:bg-gray-100"
                    )}
                  >
                    <Icon className="w-4 h-4" />
                    {label}
                  </Link>
                ))}
              </nav>
            </aside>

            {/* Overlay */}
            {sidebarOpen && (
              <div className="fixed inset-0 z-40 bg-black/30 lg:hidden" onClick={() => setSidebarOpen(false)} />
            )}

            {/* Main */}
            <div className="flex-1 flex flex-col overflow-hidden">
              <header className="bg-white border-b border-gray-200 px-4 py-3 flex items-center gap-3 lg:hidden">
                <button onClick={() => setSidebarOpen(true)}>
                  <Menu className="w-5 h-5" />
                </button>
                <span className="font-semibold text-blue-600">Maga</span>
              </header>
              <main className="flex-1 overflow-y-auto p-6">
                {children}
              </main>
            </div>
          </div>
        </QueryClientProvider>
      </body>
    </html>
  );
}
