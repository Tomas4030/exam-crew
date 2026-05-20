'use client';

import { useState } from 'react';

export default function JsonViewer({ data }: { data: Record<string, unknown> }) {
  const [collapsed, setCollapsed] = useState(false);
  const jsonStr = JSON.stringify(data, null, 2);

  const handleDownload = () => {
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'result.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="border rounded-lg overflow-hidden">
      <div className="flex justify-between items-center p-3 bg-gray-100">
        <button onClick={() => setCollapsed(!collapsed)} className="text-sm text-blue-600 hover:underline">
          {collapsed ? 'Expandir' : 'Colapsar'}
        </button>
        <button onClick={handleDownload} className="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
          Download JSON
        </button>
      </div>
      {!collapsed && (
        <pre className="p-4 overflow-auto text-sm bg-gray-50 max-h-[600px]">{jsonStr}</pre>
      )}
    </div>
  );
}
