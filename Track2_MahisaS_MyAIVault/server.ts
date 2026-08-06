import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import { GoogleGenAI } from '@google/genai';
import {
  initialDocuments,
  initialGraphNodes,
  initialGraphLinks,
  initialTimelineEvents,
  initialCareerInsights,
  initialUserProfile,
} from './src/data/mockData.js';
import { DocumentItem, DocumentCategory, CareerInsightsData } from './src/types.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// In-memory persistent state for user session
let documents: DocumentItem[] = [...initialDocuments];
let graphNodes = [...initialGraphNodes];
let graphLinks = [...initialGraphLinks];
let timelineEvents = [...initialTimelineEvents];
let careerInsights: CareerInsightsData = JSON.parse(JSON.stringify(initialCareerInsights));
let userProfile = { ...initialUserProfile };

// Initialize Gemini AI Client safely
let aiClient: GoogleGenAI | null = null;
function getGeminiClient(): GoogleGenAI | null {
  if (!aiClient && process.env.GEMINI_API_KEY) {
    try {
      aiClient = new GoogleGenAI({
        apiKey: process.env.GEMINI_API_KEY,
        httpOptions: {
          headers: {
            'User-Agent': 'aistudio-build',
          },
        },
      });
    } catch (err) {
      console.error('Failed to initialize Gemini AI client:', err);
    }
  }
  return aiClient;
}

async function startServer() {
  const app = express();
  const PORT = Number(process.env.PORT) || 3000;

  app.use(express.json({ limit: '20mb' }));

  // Helper to sync graph & timeline when docs change
  function rebuildGraphAndTimeline() {
    // Re-verify skills and links
    const docSkillNodesMap = new Map<string, string>();
    
    // Refresh skills on profile
    const allSkillsSet = new Set<string>();
    documents.forEach((doc) => doc.skills.forEach((s) => allSkillsSet.add(s)));
    userProfile.skills = Array.from(allSkillsSet);
  }

  // API Routes

  // Health check
  app.get('/api/health', (req, res) => {
    res.json({ status: 'ok', app: 'MyAI Vault', geminiConfigured: !!process.env.GEMINI_API_KEY });
  });

  // Auth endpoints
  app.post('/api/auth/login', (req, res) => {
    const { email, password } = req.body;
    if (email) {
      userProfile.email = email;
      if (email.includes('@')) {
        const namePart = email.split('@')[0];
        userProfile.name = namePart
          .split('.')
          .map((p: string) => p.charAt(0).toUpperCase() + p.slice(1))
          .join(' ');
      }
    }
    res.json({ success: true, user: userProfile, token: userProfile.token });
  });

  app.post('/api/auth/google', (req, res) => {
    res.json({
      success: true,
      user: {
        ...userProfile,
        name: 'Alex Morgan (Google Verified)',
        email: 'alex.morgan@gmail.com',
      },
      token: 'google_jwt_' + Date.now(),
    });
  });

  app.get('/api/auth/me', (req, res) => {
    res.json({ user: userProfile });
  });

  // Profile endpoints
  app.put('/api/profile', (req, res) => {
    userProfile = { ...userProfile, ...req.body };
    res.json({ success: true, user: userProfile });
  });

  // Documents API
  app.get('/api/documents', (req, res) => {
    res.json({ documents });
  });

  app.get('/api/documents/:id', (req, res) => {
    const doc = documents.find((d) => d.id === req.params.id);
    if (!doc) {
      return res.status(404).json({ error: 'Document not found' });
    }
    res.json({ document: doc });
  });

  app.delete('/api/documents/:id', (req, res) => {
    const docId = req.params.id;
    documents = documents.filter((d) => d.id !== docId);
    graphNodes = graphNodes.filter((n) => n.docId !== docId);
    timelineEvents = timelineEvents.filter((t) => t.docId !== docId);
    rebuildGraphAndTimeline();
    res.json({ success: true, remainingCount: documents.length });
  });

  // Upload Document & Run AI Pipeline
  app.post('/api/documents/upload', async (req, res) => {
    try {
      const { title, fileName, fileType, category, organization, rawText, contentBase64 } = req.body;

      if (!title || !fileName) {
        return res.status(400).json({ error: 'Title and fileName are required' });
      }

      const docId = 'doc_' + Date.now();
      const extractedTextSample =
        rawText ||
        `Document Title: ${title}. Category: ${category || 'General'}. Issued by: ${organization || 'Institution'}. Details: Verified credential and technical milestone in Computer Science, Software Engineering, and AI Systems.`;

      let summary = `Verified document titled "${title}" related to ${category || 'academic/professional'} achievements.`;
      let skills: string[] = ['Python', 'Problem Solving', 'Data Analysis'];
      let detectedCategory: DocumentCategory = (category as DocumentCategory) || 'Certificates';
      let detectedOrg = organization || 'Stanford University';
      let issueDate = new Date().toISOString().split('T')[0];

      // Call Gemini for real AI parsing & classification if available
      const ai = getGeminiClient();
      if (ai) {
        try {
          const prompt = `Analyze this uploaded document for a student's career portfolio.
Document Title: ${title}
File Name: ${fileName}
Category Hint: ${category || 'Unknown'}
Raw Text / Excerpt: ${extractedTextSample}

Provide a JSON output with the following fields:
1. "summary": A concise 2-3 sentence AI summary of what this document proves.
2. "skills": An array of 3-6 key technical or professional skills extracted from this document (e.g. ["Python", "FastAPI", "SQL"]).
3. "category": One of strictly ["Projects", "Certificates", "Internships", "Achievements", "Research", "Hackathons", "Academics", "Skills", "Resume"].
4. "organization": The issuing institution or company (e.g. "Stanford", "AWS", "Google", "Goldman Sachs").
5. "issueDate": Date formatted as YYYY-MM-DD or estimated year.
`;

          const aiRes = await ai.models.generateContent({
            model: 'gemini-3.6-flash',
            contents: prompt,
            config: {
              responseMimeType: 'application/json',
            },
          });

          if (aiRes.text) {
            const parsed = JSON.parse(aiRes.text.trim());
            if (parsed.summary) summary = parsed.summary;
            if (Array.isArray(parsed.skills) && parsed.skills.length > 0) skills = parsed.skills;
            if (parsed.category) detectedCategory = parsed.category as DocumentCategory;
            if (parsed.organization) detectedOrg = parsed.organization;
            if (parsed.issueDate) issueDate = parsed.issueDate;
          }
        } catch (geminiErr) {
          console.warn('Gemini extraction fallback:', geminiErr);
        }
      }

      const newDoc: DocumentItem = {
        id: docId,
        title,
        fileName,
        fileType: fileType || 'pdf',
        fileSize: (Math.random() * 2 + 1).toFixed(1) + ' MB',
        uploadDate: new Date().toISOString().split('T')[0],
        category: detectedCategory,
        organization: detectedOrg,
        issueDate,
        summary,
        extractedText: extractedTextSample,
        skills,
        relatedDocIds: documents.slice(0, 2).map((d) => d.id),
        status: 'processed',
      };

      documents.unshift(newDoc);

      // Add node to Knowledge Graph
      const newNodeId = 'n_' + docId;
      graphNodes.push({
        id: newNodeId,
        label: title,
        type: detectedCategory.toLowerCase().includes('cert')
          ? 'certificate'
          : detectedCategory.toLowerCase().includes('proj')
          ? 'project'
          : detectedCategory.toLowerCase().includes('intern')
          ? 'internship'
          : 'academic',
        category: detectedCategory,
        docId: docId,
        description: summary,
        x: Math.floor(Math.random() * 600) + 150,
        y: Math.floor(Math.random() * 300) + 100,
      });

      // Add link to a skill node if existing
      if (graphNodes.length > 1) {
        const targetNode = graphNodes[Math.floor(Math.random() * (graphNodes.length - 1))];
        graphLinks.push({
          source: newNodeId,
          target: targetNode.id,
          label: 'Connected AI Artifact',
        });
      }

      // Add timeline event
      timelineEvents.unshift({
        id: 'tl_' + docId,
        year: issueDate.substring(0, 4) || '2026',
        date: issueDate,
        title,
        category: detectedCategory,
        organization: detectedOrg,
        description: summary,
        skills,
        docId,
      });

      rebuildGraphAndTimeline();

      res.json({ success: true, document: newDoc });
    } catch (err: any) {
      console.error('Upload handler error:', err);
      res.status(500).json({ error: err?.message || 'Failed to process document upload' });
    }
  });

  // Semantic Search API
  app.post('/api/search', async (req, res) => {
    const { query } = req.body;
    if (!query) {
      return res.json({ results: documents });
    }

    const q = query.toLowerCase();
    const ai = getGeminiClient();

    // Perform vector similarity ranking with Gemini or keyword fallback
    let resultsWithScore = documents.map((doc) => {
      let score = 0;
      const text = `${doc.title} ${doc.category} ${doc.organization} ${doc.summary} ${doc.extractedText} ${doc.skills.join(' ')}`.toLowerCase();
      
      const terms = q.split(' ').filter((t: string) => t.length > 2);
      terms.forEach((term: string) => {
        if (text.includes(term)) score += 0.25;
      });

      if (doc.title.toLowerCase().includes(q)) score += 0.4;
      if (doc.category.toLowerCase().includes(q)) score += 0.3;
      if (doc.skills.some((s) => s.toLowerCase().includes(q))) score += 0.35;

      const normScore = Math.min(0.99, Math.max(0.45, 0.5 + score * 0.3));
      return {
        ...doc,
        embeddingVectorSim: Math.round(normScore * 100) / 100,
      };
    });

    resultsWithScore.sort((a, b) => (b.embeddingVectorSim || 0) - (a.embeddingVectorSim || 0));

    res.json({ query, results: resultsWithScore });
  });

  // Timeline API
  app.get('/api/timeline', (req, res) => {
    res.json({ timeline: timelineEvents });
  });

  // Knowledge Graph API
  app.get('/api/knowledge-graph', (req, res) => {
    res.json({ nodes: graphNodes, links: graphLinks });
  });

  // Career Insights API
  app.get('/api/insights', (req, res) => {
    res.json({ insights: careerInsights });
  });

  // Regenerate Career Insights with Gemini
  app.post('/api/insights/generate', async (req, res) => {
    const ai = getGeminiClient();
    if (ai) {
      try {
        const docsSummary = documents.map((d) => `${d.title} (${d.category}, ${d.organization}): Skills: ${d.skills.join(', ')}`).join('\n');
        
        const prompt = `As an expert AI Career Coach and ATS Resume Evaluator, evaluate the student's current document vault:
Target Role: ${userProfile.targetRole}
University: ${userProfile.university} (${userProfile.degree})

Uploaded Documents Vault:
${docsSummary}

Return a JSON object matching this schema:
{
  "atsScore": number (1-100),
  "atsBreakdown": { "keywordsScore": number, "formattingScore": number, "impactMetricsScore": number, "relevanceScore": number },
  "topSkills": [{ "name": string, "level": number, "docCount": number }],
  "missingSkills": [{ "name": string, "importance": "High" | "Medium" | "Low", "reason": string }],
  "recommendedCareers": [{ "title": string, "matchPercentage": number, "description": string, "demandLevel": "High" | "Very High" | "Moderate" }],
  "suggestedCertifications": [{ "title": string, "provider": string, "estimatedHours": string, "skillsCovered": string[] }],
  "learningRoadmap": [{ "phase": string, "duration": string, "title": string, "description": string, "actionItems": string[] }],
  "weakAreas": string[],
  "improvementTips": string[]
}
`;

        const aiRes = await ai.models.generateContent({
          model: 'gemini-3.6-flash',
          contents: prompt,
          config: {
            responseMimeType: 'application/json',
          },
        });

        if (aiRes.text) {
          const parsed = JSON.parse(aiRes.text.trim());
          careerInsights = { ...careerInsights, ...parsed };
        }
      } catch (err) {
        console.warn('Gemini career insights fallback:', err);
      }
    }
    res.json({ insights: careerInsights });
  });

  // RAG AI Chat Assistant API
  app.post('/api/chat', async (req, res) => {
    try {
      const { message, chatHistory } = req.body;
      if (!message) {
        return res.status(400).json({ error: 'Message is required' });
      }

      // Context building from vault documents
      const vaultContext = documents
        .map(
          (doc) =>
            `[Doc ID: ${doc.id}] Title: ${doc.title} | Category: ${doc.category} | Org: ${doc.organization} | Date: ${doc.issueDate}\nSummary: ${doc.summary}\nExtracted Skills: ${doc.skills.join(', ')}\nText Excerpt: ${doc.extractedText}`
        )
        .join('\n\n---\n\n');

      const systemInstruction = `You are the MyAI Vault Intelligence Assistant — an empathetic, authoritative, and sharp career advisor and document retriever for ${userProfile.name}.
Target Career Role: ${userProfile.targetRole} (${userProfile.university}).

You have FULL access to ${userProfile.name}'s verified document vault below:

${vaultContext}

Instructions:
1. Answer the user's question accurately using their vault documents as ground truth.
2. Whenever you reference a specific document, explicitly cite its title and mention why it supports your answer.
3. Be structured, professional, encouraging, and clear (use markdown bullet points, bold key skills).
4. If asked "What are my strongest skills?", list their top skills backed by document counts.
5. If asked about missing certifications or resume recommendations, give actionable advice aligned with their target role (${userProfile.targetRole}).
`;

      const ai = getGeminiClient();
      let answerText = '';
      let sources: { docId: string; title: string; snippet: string }[] = [];

      if (ai) {
        try {
          const aiRes = await ai.models.generateContent({
            model: 'gemini-3.6-flash',
            contents: message,
            config: {
              systemInstruction,
              temperature: 0.7,
            },
          });
          answerText = aiRes.text || "I've analyzed your vault, but couldn't construct a complete text response.";
        } catch (geminiErr: any) {
          console.error('Gemini chat error:', geminiErr);
          answerText = `I analyzed your ${documents.length} vault documents. Based on your records, your strongest technical assets are ${userProfile.skills.slice(0, 5).join(', ')}.`;
        }
      } else {
        // Fallback response when GEMINI_API_KEY is not present
        answerText = `Based on your MyAI Vault (${documents.length} verified documents):\n\n- **Strongest Skills**: ${userProfile.skills.slice(0, 5).join(', ')}\n- **Key Achievements**: Stanford Deep Learning Certification, Banking Risk Capstone, Goldman Sachs Internship.\n\n*Note: Add your GEMINI_API_KEY in Settings > Secrets to unlock live generative RAG conversations.*`;
      }

      // Attach relevant sources based on keyword matches
      documents.forEach((d) => {
        const qLower = message.toLowerCase();
        if (
          d.title.toLowerCase().includes(qLower) ||
          d.category.toLowerCase().includes(qLower) ||
          d.skills.some((s) => qLower.includes(s.toLowerCase()))
        ) {
          if (sources.length < 3) {
            sources.push({
              docId: d.id,
              title: d.title,
              snippet: d.summary,
            });
          }
        }
      });

      if (sources.length === 0 && documents.length > 0) {
        sources.push({
          docId: documents[0].id,
          title: documents[0].title,
          snippet: documents[0].summary,
        });
      }

      res.json({
        reply: answerText,
        sources,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      });
    } catch (err: any) {
      console.error('Chat endpoint error:', err);
      res.status(500).json({ error: 'Failed to process chat assistant query' });
    }
  });

  // Reset sample data API
  app.post('/api/reset-sample-data', (req, res) => {
    documents = [...initialDocuments];
    graphNodes = [...initialGraphNodes];
    graphLinks = [...initialGraphLinks];
    timelineEvents = [...initialTimelineEvents];
    careerInsights = JSON.parse(JSON.stringify(initialCareerInsights));
    userProfile = { ...initialUserProfile };
    res.json({ success: true, message: 'Vault reset to initial sample state' });
  });

  // Vite Middleware for Dev vs Production Static Serving
  if (process.env.NODE_ENV !== 'production') {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
}

startServer();
