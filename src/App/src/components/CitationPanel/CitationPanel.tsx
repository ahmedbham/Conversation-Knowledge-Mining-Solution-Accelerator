import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Stack } from '@fluentui/react';
import { DismissRegular } from '@fluentui/react-icons';
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import { useAppContext } from '../../state/useAppContext';
import { actionConstants } from '../../state/ActionConstants';
import { summarizeConversation } from '../../api/api';
import "./CitationPanel.css";

interface Props {
    activeCitation: any
}

const CitationPanel = ({ activeCitation }: Props) => {
    const { dispatch } = useAppContext()
    const [summary, setSummary] = useState<string | null>(null);
    const [isSummarizing, setIsSummarizing] = useState(false);
    const [summarizeError, setSummarizeError] = useState<string | null>(null);

    const onCloseCitation = () => {
        setSummary(null);
        setSummarizeError(null);
        dispatch({ type: actionConstants.UPDATE_CITATION, payload: { activeCitation: null, showCitation: false } })
    }

    const onSummarize = async () => {
        setSummary(null);
        setSummarizeError(null);
        setIsSummarizing(true);
        try {
            const result = await summarizeConversation(activeCitation?.content || "");
            setSummary(result.summary);
        } catch {
            setSummarizeError("Failed to generate summary. Please try again.");
        } finally {
            setIsSummarizing(false);
        }
    };

    return (
        <div className='citationPanel'>
            <Stack.Item>
                <Stack
                    horizontal
                    horizontalAlign="space-between"
                    verticalAlign="center"
                >
                    <div
                        role="heading"
                        aria-level={2}
                        style={{
                            fontWeight: "600",
                            fontSize: '16px'
                        }}
                    >
                        Citations
                    </div>
                    <DismissRegular
                        role="button"
                        onKeyDown={(e) =>
                            e.key === " " || e.key === "Enter"
                                ? onCloseCitation()
                                : () => { }
                        }
                        tabIndex={0}
                        onClick={onCloseCitation}
                    />
                </Stack>
                <h5>
                    {activeCitation.title}
                </h5>
                <button
                    onClick={onSummarize}
                    disabled={isSummarizing}
                    className="summarize-button"
                    aria-label="Summarize conversation"
                >
                    {isSummarizing ? "Summarizing..." : "✨ Summarize"}
                </button>
                {summarizeError && (
                    <div className="summarize-error" role="alert">
                        {summarizeError}
                    </div>
                )}
                {summary && (
                    <div className="summarize-result">
                        <div className="summarize-result-header">Summary</div>
                        <ReactMarkdown
                            children={summary}
                            remarkPlugins={[remarkGfm]}
                            rehypePlugins={[rehypeRaw]}
                        />
                    </div>
                )}
                <ReactMarkdown
                    children={activeCitation?.content}
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[rehypeRaw]}
                />
            </Stack.Item>
        </div>)
};

export default CitationPanel;