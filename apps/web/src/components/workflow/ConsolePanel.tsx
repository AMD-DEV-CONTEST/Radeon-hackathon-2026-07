import React, { useEffect } from 'react';
import { useWorkflowStore } from '../../store/workflowStore';
import { Terminal, Trash2, ChevronUp, ChevronDown, X } from 'lucide-react';

export function ConsolePanel() {
  const {
    executionLogs,
    clearExecutionLogs,
    isRunning,
    consoleExpanded,
    setConsoleExpanded,
    consoleFilterNodeId,
    setConsoleFilterNodeId,
  } = useWorkflowStore();
  const consoleRef = React.useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isRunning) setConsoleExpanded(true);
  }, [isRunning, setConsoleExpanded]);

  const filteredLogs = consoleFilterNodeId
    ? executionLogs.filter((l) => l.nodeId === consoleFilterNodeId || l.nodeId === '')
    : executionLogs;

  useEffect(() => {
    if (consoleRef.current && consoleExpanded) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
    }
  }, [filteredLogs, consoleExpanded]);

  const getLevelColor = (level: string) => {
    switch (level) {
      case 'info':
        return 'text-blue-400';
      case 'warn':
        return 'text-yellow-400';
      case 'error':
        return 'text-red-400';
      case 'success':
        return 'text-green-400';
      default:
        return 'text-muted-foreground';
    }
  };

  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  return (
    <div
      className={`border-t bg-card flex flex-col shrink-0 transition-all duration-200 ${
        consoleExpanded ? 'h-48' : 'h-9'
      }`}
    >
      <button
        type="button"
        className="px-4 py-2 border-b flex items-center justify-between w-full hover:bg-muted/50 transition-colors shrink-0"
        onClick={() => setConsoleExpanded(!consoleExpanded)}
      >
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-muted-foreground" />
          <span className="text-sm font-medium">Console</span>
          <span className="text-xs text-muted-foreground">
            ({filteredLogs.length}
            {consoleFilterNodeId ? ' filtered' : ''} logs)
          </span>
          {consoleFilterNodeId && (
            <span
              className="text-xs text-primary flex items-center gap-1"
              onClick={(e) => {
                e.stopPropagation();
                setConsoleFilterNodeId(null);
              }}
            >
              筛选中
              <X className="w-3 h-3" />
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {consoleExpanded && executionLogs.length > 0 && (
            <span
              role="button"
              tabIndex={0}
              className="p-1.5 rounded hover:bg-muted"
              title="Clear console"
              onClick={(e) => {
                e.stopPropagation();
                clearExecutionLogs();
              }}
              onKeyDown={(e) => e.key === 'Enter' && clearExecutionLogs()}
            >
              <Trash2 className="w-3.5 h-3.5 text-muted-foreground" />
            </span>
          )}
          {consoleExpanded ? (
            <ChevronDown className="w-4 h-4 text-muted-foreground" />
          ) : (
            <ChevronUp className="w-4 h-4 text-muted-foreground" />
          )}
        </div>
      </button>

      {consoleExpanded && (
        <div
          ref={consoleRef}
          className="flex-1 overflow-y-auto p-3 font-mono text-xs space-y-1 min-h-0"
        >
          {filteredLogs.length === 0 ? (
            <div className="text-muted-foreground text-center py-6">
              <p>运行日志将显示在这里</p>
              <p className="text-xs mt-1">点击 Run 开始执行</p>
            </div>
          ) : (
            filteredLogs.map((log, index) => (
              <div key={index} className="flex gap-2">
                <span className="text-muted-foreground shrink-0">
                  [{formatTime(log.timestamp)}]
                </span>
                <span className={getLevelColor(log.level)}>
                  [{log.level.toUpperCase()}]
                </span>
                <span className="text-foreground">{log.message}</span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
