import React, { useEffect, useState, useRef } from 'react';
import { Send, Users, Activity } from 'lucide-react';
import { api } from '../api/client';
import { CommunityMessage } from '../api/types';
import { useAuth } from '../context/AuthContext';
import { useMeshEvent } from '../api/ws';

export const CommunityView: React.FC = () => {
  const { user } = useAuth();
  const [messages, setMessages] = useState<CommunityMessage[]>([]);
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);

  const loadMessages = async () => {
    try {
      const resp = await api.getCommunityMessages();
      setMessages(resp.data);
      scrollToBottom();
    } catch (err) {
      console.error('Failed to load community messages', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMessages();
  }, []);

  useMeshEvent('community.message_sent', (msg: CommunityMessage) => {
    setMessages(prev => {
      if (prev.find(m => m.id === msg.id)) return prev;
      return [...prev, msg];
    });
    scrollToBottom();
  });

  const scrollToBottom = () => {
    setTimeout(() => {
      if (feedRef.current) {
        feedRef.current.scrollTop = feedRef.current.scrollHeight;
      }
    }, 50);
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!content.trim()) return;

    setSending(true);
    try {
      const newMsg = await api.sendCommunityMessage(content);
      setMessages(prev => {
        if (prev.find(m => m.id === newMsg.id)) return prev;
        return [...prev, newMsg];
      });
      setContent('');
      scrollToBottom();
    } catch (err: any) {
      alert(err.message);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
        <div>
          <h2 className="text-xl font-bold text-main leading-tight flex items-center gap-2">
            <Users className="text-accent" />
            Community Dispatch
          </h2>
          <p className="text-sm text-muted mt-1">
            Global public broadcast channel for responder and civilian coordination.
          </p>
        </div>
      </div>

      <div className="flex-1 min-h-0 bg-surface border border-separator rounded-lg overflow-hidden flex flex-col shadow-sm">
        <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4" ref={feedRef}>
          {loading ? (
            <div className="flex justify-center items-center h-full text-muted">
              <Activity className="animate-spin mr-2" size={18} /> Syncing mesh comms...
            </div>
          ) : messages.length === 0 ? (
            <div className="flex justify-center items-center h-full text-muted">
              No active broadcasts in the community.
            </div>
          ) : (
            messages.map(msg => {
              const isMe = user?.id === msg.sender_id;
              
              return (
                <div key={msg.id} className={`flex flex-col ${isMe ? 'items-end' : 'items-start'} max-w-[85%] ${isMe ? 'ml-auto' : ''}`}>
                  <span className="text-xs font-medium text-muted mb-1 px-1">
                    {isMe ? 'You' : `@${msg.sender_username}`}
                  </span>
                  <div 
                    className={`px-4 py-2 text-sm leading-relaxed max-w-full break-words
                      ${isMe 
                        ? 'bg-accent text-white rounded-2xl rounded-br-sm' 
                        : 'bg-body border border-separator text-main rounded-2xl rounded-bl-sm'
                      }`}
                  >
                    {msg.content}
                  </div>
                  <span className="text-[10px] text-muted/70 mt-1 px-1 font-mono uppercase tracking-wider">
                    {new Date(msg.sent_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
              );
            })
          )}
        </div>

        <div className="p-3 bg-surface border-t border-separator">
          <form onSubmit={handleSend} className="flex gap-2">
            <input
              type="text"
              value={content}
              onChange={e => setContent(e.target.value)}
              disabled={sending}
              placeholder="Broadcast to community..."
              className="flex-1 bg-body border border-separator rounded-full px-4 py-2 text-sm text-main focus:outline-none focus:border-accent transition-colors disabled:opacity-50"
              autoComplete="off"
            />
            <button
              type="submit"
              disabled={!content.trim() || sending}
              className="bg-accent text-white p-2 px-4 rounded-full flex items-center justify-center hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Send size={18} className={sending ? "animate-pulse" : ""} />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};
