// 🔑 Google OAuth Credentials Configuration Setup
// Paste your production web application client key string from your Google Cloud Console here
const GOOGLE_CLIENT_ID = "424486537653-6a42le0pu2s0tn4m0re640orssg43pj6.apps.googleusercontent.com";

const FALLBACK_AVATAR = "https://lh3.googleusercontent.com/aida-public/AB6AXuCtBpV71QtTo17hmuGO2wIHqo62c3izFoKE5XQuFilvfhvJ3XWvENNbR_xv24kR1qb4eJXyQaunacmYW7byLNltRAaI-lPVbtFRnt3TTubuS59iuGGbC6xsypQoYVynfEsYnuLkFv_JDOu-_CfeidHGdkvJRGSIhTpoiP_ZoOyaOpDaVqHN_ns6AQhPTJiRA_NudBKFlYVfodU4ZzeokFuBHyiWsVVQYlKP60yf1bCG10Ma7iHSJh_p";

let toastRemovalTimer = null;
  
const DEFAULT_PROFILE = {
    name: "Arpita Robert",
    team: "Team Innovators",
    avatar: "/assets/images/sampleUserPictureAliveAI.png" // Default image path
};

const categoryMediaAssets = {
  education: {
    badgeText: "EDUCATION",
    mainPreview: "/assets/images/pictureAliveAI_mainPanelView.png",
    thumbnails: [
      "/assets/images/pictureAliveAI_Education1.png",
      "/assets/images/pictureAliveAI_Education2.png",
      "/assets/images/pictureAliveAI_Education3.png",
      "/assets/images/pictuteAliveAI_Education4.png" // Preserved your typo path token
    ]
  },
  accessibility: {
    badgeText: "ACCESSIBILITY",
    mainPreview: "/assets/images/pictureAliveAI_AccessibilityMain.png",
    thumbnails: [
      "/assets/images/pictureAliveAI_Access1.png",
      "/assets/images/pictureAliveAI_Access2.png",
      "/assets/images/pictureAliveAI_Access3.png",
      "/assets/images/pictureAliveAI_Access4.png"
    ]
  },
  heritage_tourism: {
    badgeText: "HERITAGE & TOURISM",
    mainPreview: "/assets/images/pictureAliveAI_HeritageMain.png",
    thumbnails: [
      "/assets/images/pictureAliveAI_Heritage1.png",
      "/assets/images/pictureAliveAI_Heritage2.png",
      "/assets/images/pictureAliveAI_Heritage3.png",
      "/assets/images/pictureAliveAI_Heritage4.png"
    ]
  },
  digital_world: {
    badgeText: "DIGITAL WORLD",
    mainPreview: "/assets/images/pictureAliveAI_DigitalMain.png",
    thumbnails: [
      "/assets/images/pictureAliveAI_Digital1.png",
      "/assets/images/pictureAliveAI_Digital2.png",
      "/assets/images/pictureAliveAI_Digital3.png",
      "/assets/images/pictureAliveAI_Digital4.png"
    ]
  },
  content_creation: {
    badgeText: "CONTENT CREATION",
    mainPreview: "/assets/images/pictureAliveAI_ContentMain.png",
    thumbnails: [
      "/assets/images/pictureAliveAI_Content1.png",
      "/assets/images/pictureAliveAI_Content2.png",
      "/assets/images/pictureAliveAI_Content3.png",
      "/assets/images/pictureAliveAI_Content4.png"
    ]
  }
};



document.addEventListener('DOMContentLoaded', () => {
  const navItems = document.querySelectorAll('[data-nav-item]');
  const helpBtn = document.getElementById('helpEmailTrigger');

	const menuTabs = document.querySelectorAll('.nav-item');
  const mainPreviewImg = document.getElementById('main-preview');
  const categoryBadge = document.getElementById('categoryBadge');
  const thumbnailRow = document.getElementById('thumbnailRow');
  const scrubberFill = document.getElementById('scrubberFill');

	 // ⚙️ STATE FLAGS CONTROL MATRIX (Verification Metrics)
  let isStoryGenerated = false; 
  let targetUploadedFile = null;
  
  // ⚙️ System state configurations tracking metrics
  let activeSelectedMode = 'heritage_tourism'; // Matches your startup layout state defaults
  let activeAudioTrackBlobUrl = null;
  let targetUploadedFileBlob = null; // Stores the file for later execution

  let lastGeneratedFilename = null;
  // binary audio file blob into memory the exact millisecond it arrives from your backend!
  let successfullyCompiledAudioBlobCache = null; 
  // Interface selectors
  const leftPanelDownloadBtn = document.querySelector('button.action-item[data-action="download"]');
 // 🎯 Target the share button using its specific data-action attribute
  const leftPanelShareBtn = document.querySelector('button.action-item[data-action="share"]');
  const shareModalOverlay = document.getElementById('jsShareModalOverlay');
  const closeShareModalBtn = document.getElementById('jsCloseShareModalBtn');
  
  // Select layout element target nodes
  const hiddenAudioNode = document.getElementById('hiddenPreviewAudio');
  const playPreviewBtn = document.getElementById('playPreview');
  const mainPlayIcon = document.getElementById('mainPlayIcon');
  const scrubberTrack = document.getElementById('previewScrubberTrack');
   const uploaderCard = document.getElementById('uploaderStateWorkspace');
  
   // Select interface DOM element node tracks
  const uploaderWorkspace = document.getElementById('uploaderStateWorkspace');
  const storyWorkspace = document.getElementById('storyOutputStateWorkspace');
  const dropZone = document.getElementById('dropZoneArea');
  const fileInput = document.getElementById('hiddenFileInput');
  const generateBtn = document.getElementById('executeGenerationTrigger');
  const revertBtn = document.getElementById('revertToUploadBtn');
  const storyTextField = document.getElementById('dynamicStoryTextContent');
 
   let previewAnimating = false;
   
   // ==========================================================================
// 🧠 INTERNAL MULTIMODAL AI THOUGHT ENGINE (Compact Cyberpunk Fragments)
// ==========================================================================
const MULTIMODAL_AI_THOUGHTS_MATRIX = [
   "“The power of multimodal AI lies not in how it reads pixels, but in how it pieces together the human stories hidden behind them.”",
  "“Art and technology do not collide here; they synchronize to breathe voice into static canvases, making memory a living medium.”",
  "“When vision data blends perfectly with synchronized neural speech vectors, data ceases to be cold numbers and becomes pure imagination.”",
  "“Multimodal comprehension is the bridge that allows modern machines to look at a photograph, understand its soul, and narrate its history.”",
  "“Every image uploaded is a frozen fragment of time waiting for artificial intelligence to unseal its voice and animate its layout path.”",
  "“Innovation is the constant translation of silent pixels into high-fidelity audible frequencies that resonate across human experience.”"
];

// 🎯 Target the premium regenerate button using its precise data-action attribute
  const regenerateBtn = document.querySelector('button.action-item[data-action="regenerate"]');
  let isUserCustomUploadStaged = false; 	
  
  // 1. Initial State Orchestrator Check (Forces Uploader View On Page Load Natively)
  evaluateActiveViewState();

  // 2. Drag & Drop Event Handlers
  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
  });

  dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drag-over');
  });
  
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const droppedFiles = e.dataTransfer.files;
    if (droppedFiles.length > 0) {
      processSelectedFileAsset(droppedFiles[0]);
    }
  });
  
  // 3. File Input Change Trigger
  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      processSelectedFileAsset(e.target.files[0]);
    }
  });

 // ==========================================================================
  // 📥 BULLETPROOF FRONTEND DOWNLOAD HANDLER (Instant Memory Saving Execution)
  // ==========================================================================
  if (leftPanelDownloadBtn) {
    leftPanelDownloadBtn.onclick = function(event) {
      event.preventDefault();
      event.stopImmediatePropagation();  // Forces mock scripts to drop processing hooks completely
      
      console.log("📥 [Download System]: Initializing instant, non-blocking local memory download extraction...");

       // 🛑 1. SAFETY GUARD CHECK: Reject if no media binary has been compiled yet
      if (!successfullyCompiledAudioBlobCache || successfullyCompiledAudioBlobCache.size === 0) {
        console.warn("⚠️ [Download Blocked]: No binary cached in RAM. Firing toast and vocal alert tracks.");
        
        const sampleValidationBlockText = "No active media generated yet! Please select an image and click 'Generate AI Story' first.";

        // Clear out any stale text strings inside your active toast system if applicable
        if (typeof clearAllActiveToasts === 'function') {
          clearAllActiveToasts();
        }

        // Fire your custom warning notice strings
        if (typeof showToast === 'function') {
          showToast(sampleValidationBlockText);
        } else if (typeof triggerPremiumSystemToast === 'function') {
          triggerPremiumSystemToast(sampleValidationBlockText);
        } else {
          alert(sampleValidationBlockText);
        }

        // 🎯 🆂 THE AUDIO VOICE-OVER ATTACHMENT: Say it out loud natively!
        if ('speechSynthesis' in window) {
          window.speechSynthesis.cancel(); // Drop any playing vocal buffers to prevent overlaps
          
          const warningUtterance = new SpeechSynthesisUtterance("No active media.");
          const availableSystemVoices = window.speechSynthesis.getVoices();
          const localizedVoiceMatch = availableSystemVoices.find(voice => voice.lang.includes('en'));
          if (localizedVoiceMatch) {
            warningUtterance.voice = localizedVoiceMatch;
          }
          
          warningUtterance.rate = 1.05;  // Crisp, professional alert speed
          warningUtterance.pitch = 1.0;  // Standard neutral informative tone pitch
          
          window.speechSynthesis.speak(warningUtterance);
          console.log("🔊 [Text-To-Speech Alert]: Dispatched warning announcement audio vectors.");
        }
        
        return; // Terminate execution line instantly. No file task is run!
      }

      try {
        // 🛠️ Step A: Isolate the unique 12-character alphanumeric hash code from the string
        let fileHashFragment = "PREVIEW";
        if (lastGeneratedFilename) {
          const hashMatch = lastGeneratedFilename.match(/speech_(.*?)\.wav/i);
          if (hashMatch && hashMatch[1]) {
            fileHashFragment = hashMatch[1].toUpperCase(); 
          }
        }

        // 🛠️ Step B: Format the active navigation sidebar category selection tag cleanly
        const formattedModeLabel = activeSelectedMode.replace(/_/g, "-").toUpperCase();

        // 🎯 CUSTOM APPLICATION NAME SIGNATURE CONVENTION
        // Compiles exactly: PICTURE-ALIVE-AI_HERITAGE-TOURISM_0CD25147E121_4K.wav
        const customApplicationFilename = `PICTURE-ALIVE-AI_${formattedModeLabel}_${fileHashFragment}_4K.wav`;

        console.log(`💾 [Formatting Output Filename]: "${customApplicationFilename}"`);

        // 🎯 THE BYPASS: Turn the pre-saved memory binary blob directly into a clean, local file download link
        const localDownloadReferenceUrl = window.URL.createObjectURL(successfullyCompiledAudioBlobCache);

        // 🛠️ Step C: Build an isolated, invisible HTML anchor link node in memory
        const virtualDownloadAnchor = document.createElement('a');
        virtualDownloadAnchor.href = localDownloadReferenceUrl;

        // Force the browser to rename the file signature custom layout format name tag
        virtualDownloadAnchor.setAttribute('download', customApplicationFilename);
        
        // Keep it hidden outside the layout trees to prevent visual layout shifts
        virtualDownloadAnchor.style.display = 'none';
        document.body.appendChild(virtualDownloadAnchor);

        // 💥 Fire the physical browser download window save dialogue window trigger event
        virtualDownloadAnchor.click();

        // 🧹 Garbage Collection Layer: Immediately clear allocated local reference tracks
        document.body.removeChild(virtualDownloadAnchor);
        window.URL.revokeObjectURL(localDownloadReferenceUrl); // Frees local system RAM allocations instantly
        
        console.log("✅ [Local Download Success]: File payload written to system downloads directory successfully.");
        if (typeof showToast === 'function') {
          showToast("Download started successfully!");
        }

      } catch (downloadExceptionErr) {
        console.error("❌ [Download Exception Fault]: Data file renaming track failed:", downloadExceptionErr);
        
        // 🚀 CRITICAL EMERGENCY FALLBACK LINK: Direct Route to your Python File server if local RAM tracking stalls
        if (lastGeneratedFilename) {
          console.log("📡 [Download Fallback]: Fetching raw file attachment link directly from FastAPI backend...");
          const fallbackUrl = `http://127.0.0{lastGeneratedFilename}`;
          const fallbackAnchor = document.createElement('a');
          fallbackAnchor.href = fallbackUrl;
          fallbackAnchor.setAttribute('download', `PICTURE-ALIVE-AI_${activeSelectedMode.toUpperCase()}_4K.wav`);
          fallbackAnchor.style.display = 'none';
          document.body.appendChild(fallbackAnchor);
          fallbackAnchor.click();
          document.body.removeChild(fallbackAnchor);
        }
      }
    };
  }

	  
// ==========================================================================
// 🛸 ANTI-INTERCEPTION PRODUCTION GLOBAL SHARE CONTROLLER ENGINE
// ==========================================================================
window.launchAppProductionShare = function(event) {
  if (event) {
    event.preventDefault();
    // 🎯 THE PRIORITY SHIELD FIX:
    // Instantly freezes the event so no external or mock scripts can fire false toasts!
    event.stopImmediatePropagation();  // Stops external mock framework interception hooks completely
  }

  console.log("🛸 [Share System]: Extracting production state properties for social broadcast...");

  const shareModalOverlay = document.getElementById('jsShareModalOverlay');
  const closeShareModalBtn = document.getElementById('jsCloseShareModalBtn');

  // ==========================================================================
  // 🎯 THE PRODUCTION SYNC FIX: Using runtime trackers instead of test strings
  // ==========================================================================
  // Read state handles directly from your application's global variable trackers
  const activeModeToken = (typeof activeSelectedMode !== 'undefined' && activeSelectedMode) ? activeSelectedMode : 'heritage_tourism';
  const runtimeFilenameString = (typeof lastGeneratedFilename !== 'undefined' && lastGeneratedFilename) ? lastGeneratedFilename : '';

  // ==========================================================================
  // 🛑 SAFETY GUARD CHECK: Abort instantly if no backend sound asset has been tracked yet
  // ==========================================================================
  if (!runtimeFilenameString || runtimeFilenameString === "" || !hiddenAudioNode || !hiddenAudioNode.src || hiddenAudioNode.src === "") {
    console.warn("⚠️ [Share Blocked]: No active media array detected. Firing toast and vocal warning.");
    
    const sampleValidationBlockText = "No active media generated yet! Please click 'Generate AI Story' first, nothing to share.";

    // Clear out any stale text strings inside your active toast system if applicable
    if (typeof clearAllActiveToasts === 'function') {
      clearAllActiveToasts();
    }

    // Forcefully display your custom warning notice strings onto your viewport
    if (typeof showToast === 'function') {
      showToast(sampleValidationBlockText);
    } else if (typeof triggerPremiumSystemToast === 'function') {
      triggerPremiumSystemToast(sampleValidationBlockText);
    } else {
      alert(sampleValidationBlockText);
    }

    // 🎯 🆂 THE AUDIO VOICE-OVER FIX: Instruct the browser to say the message out loud!
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel(); // 💥 Drop any currently playing vocal buffers to prevent overlaps
      
      // Instantiate a hardware vocalization controller stream with your exact requested text
      const shareWarningUtterance = new SpeechSynthesisUtterance("No active media generated yet! Please click 'Generate AI Story' first, nothing to share.");
      
      // Select an official high-fidelity localized English voice module configuration
      const availableSystemVoices = window.speechSynthesis.getVoices();
      const localizedVoiceMatch = availableSystemVoices.find(voice => voice.lang.includes('en'));
      if (localizedVoiceMatch) {
        shareWarningUtterance.voice = localizedVoiceMatch;
      }
      
      shareWarningUtterance.rate = 1.05;  // Modern, crisp professional alert speed
      shareWarningUtterance.pitch = 0.95; // Premium cinematic warning pitch factor
      
      // Dispatch vocal stream natively down to the client machine speakers
      window.speechSynthesis.speak(shareWarningUtterance);
      console.log("A.I. Voice Engine: Dispatched hardware share restriction alert audio vectors successfully.");
    }
    
    return; // Terminate execution line instantly. No modal box layout or background toast is fired!
  }


  try {
    // 🛠️ Step A: Extract the unique text hash token from the file string name dynamically
    let fileHashFragment = "PRODUCTION";
    const hashMatch = runtimeFilenameString.match(/speech_(.*?)\.wav/i);
    if (hashMatch && hashMatch[1]) {
      fileHashFragment = hashMatch[1].toUpperCase(); // Isolates the raw text hash token beautifully
    }

    // 🛠️ Step B: Format the mode string label neatly for public presentation
    const formattedModeLabel = activeModeToken.replace(/_/g, " ").toUpperCase();
        const SERVER_URL = "http://127.0.0.1:8000";
		const AUDIO_ROUTE = "/audio_output/";
    
    // 🎯 THE CRITICAL PORT MATCHING ROUTE FIX: 
    // Combines your true backend IP (127.0.0.1), server port (:8000), and static file directory path prefix (/audio_output)
	const shareUrl = SERVER_URL + AUDIO_ROUTE + runtimeFilenameString;

    // Build the high-fidelity branding composition message string exactly as specified [1]
    const compositeMessageString = `🎧 Check out this AI narration generated by Picture Alive AI!\n\nMode: ${formattedModeLabel}\n\nListen here:\n${shareUrl}`;
    const encodedText = encodeURIComponent(compositeMessageString);

    if (!shareModalOverlay) {
      console.error("❌ [Share Error]: Could not locate '#jsShareModalOverlay' inside your index.html DOM structure layout.");
      return;
    }

    const whatsappBtnNode = document.getElementById('shareNodeWhatsApp');
    const twitterBtnNode = document.getElementById('shareNodeTwitter');
    const copyLinkBtnNode = document.getElementById('shareNodeCopyLink');

    // ==========================================================================
    // 🎯 THE DIRECT ANCHOR FIX: Bypasses window.open hijacking entirely!
    // ==========================================================================
    
    // 🟢 1. Official WhatsApp Web Cloud API Connection Gateway [1]
    if (whatsappBtnNode) {
      whatsappBtnNode.onclick = function(e) {
        e.preventDefault();
        e.stopPropagation();
        
        const targetWhatsappUrl = "https://api.whatsapp.com/send?text=" + encodedText;
        console.log("📡 [Network Outbound]: Routing direct anchor link tracking packet to WhatsApp...");

        // Build temporary element in-memory to prevent third-party text altering
        const hiddenLinkNode = document.createElement('a');
        hiddenLinkNode.href = targetWhatsappUrl;
        hiddenLinkNode.target = '_blank';
        hiddenLinkNode.rel = 'noopener noreferrer';
        
        document.body.appendChild(hiddenLinkNode);
        hiddenLinkNode.click(); // Fires a clean native browser window opening sequence [1]
        document.body.removeChild(hiddenLinkNode);
      };
    }
    
    // 🟢 2. Official Twitter / X Compositing Intent Gateway
    if (twitterBtnNode) {
      twitterBtnNode.onclick = function(e) {
        e.preventDefault();
        e.stopPropagation();
        
        const targetTwitterUrl = "https://twitter.com/intent/tweet?text=" + encodedText;
        console.log("📡 [Network Outbound]: Routing direct anchor link tracking packet to Twitter/X...");

        const hiddenLinkNode = document.createElement('a');
        hiddenLinkNode.href = targetTwitterUrl;
        hiddenLinkNode.target = '_blank';
        hiddenLinkNode.rel = 'noopener noreferrer';
        
        document.body.appendChild(hiddenLinkNode);
        hiddenLinkNode.click();
        document.body.removeChild(hiddenLinkNode);
      };
    }

    // 🟢 3. Asynchronous Clipboard Write Node (Copy Link Function)
    if (copyLinkBtnNode) {
      copyLinkBtnNode.onclick = async function(e) {
        e.preventDefault();
        e.stopPropagation();
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(compositeMessageString);
          } else {
            const fallbackTextArea = document.createElement("textarea");
            fallbackTextArea.value = compositeMessageString;
            fallbackTextArea.style.position = "fixed"; 
            document.body.appendChild(fallbackTextArea);
            fallbackTextArea.select();
            document.execCommand("copy");
            document.body.removeChild(fallbackTextArea);
          }
          
          if (typeof showToast === 'function') {
            showToast("Link copied to clipboard! Share it anywhere.");
          }
          shareModalOverlay.style.display = "none";
        } catch (err) {
          console.error("Clipboard blocked:", err);
        }
      };
    }

    // 🟢 4. The Close Button Bindings inside Function Scope
    if (closeShareModalBtn) {
      closeShareModalBtn.onclick = function(e) {
        e.preventDefault();
        console.log("🛸 [Share System]: Hiding overlay panel container...");
        shareModalOverlay.style.display = "none";
      };
    }

    // Backdrop click interceptor
    shareModalOverlay.onclick = function(e) {
      if (e.target === shareModalOverlay) {
        shareModalOverlay.style.display = "none";
      }
    };

    // 💥 DRAW THE MODAL OPTIONS CONTAINER VISIBLE
    shareModalOverlay.style.display = "flex";
    console.log("✅ [Share System]: Modal drawn on screen layout successfully.");

  } catch (productionExceptionErr) {
    console.error("❌ [Share Core Exception Fault]: Production pipeline render stalled:", productionExceptionErr);
  }
};

	  // ==========================================================================
  // 🔄 Step C: The Refined Smart Regenerate Workflow Click Handler Engine
  // ==========================================================================
  if (regenerateBtn) {
    regenerateBtn.addEventListener('click', (e) => {
      e.preventDefault();
       e.stopImmediatePropagation(); 

      console.log("🔄 [Regenerate Loop]: Evaluating environmental data validity...");

      // 🎯 THE CRITICAL SECURITY TRACK GUARD: 
      // Force exit and block if the system detects the image is just a static sample layout asset! 
    // ==========================================================================
      // 🛑 REGENERATE TRACK GUARD: Block placeholder system sample image runs
      // ==========================================================================
      if (!isUserCustomUploadStaged) {
        const sampleValidationBlockText = "Cannot regenerate response for placeholder sample images! Please upload your own custom picture file card asset first.";
        
        console.warn("⚠️ [Regenerate Blocked]: Blocked sample image run. Firing strict visual and vocal alerts.");

        // Clear out any stale text strings inside your active toast system if applicable
        if (typeof clearAllActiveToasts === 'function') {
          clearAllActiveToasts();
        }

        // 📱 Fire your custom alert notice strings onto your screen layout viewport
        if (typeof showToast === 'function') {
          showToast(sampleValidationBlockText);
        } else if (typeof triggerPremiumSystemToast === 'function') {
          triggerPremiumSystemToast(sampleValidationBlockText);
        } else {
          alert(sampleValidationBlockText);
        }

        // 🎯 🆂 THE AUDIO VOICE-OVER FIX: Say the warning phrase out loud! [2]
        if ('speechSynthesis' in window) {
          window.speechSynthesis.cancel(); // 💥 Drop any currently playing vocal buffers to prevent overlaps
          
          // Instantiate a hardware vocalization controller stream with your exact requested warning phrase [12]
          const regenerateWarningUtterance = new SpeechSynthesisUtterance("Cannot regenerate response for placeholder sample images. Please upload your own custom picture file card asset first.");
          
          // Select an official high-fidelity localized English voice module configuration [12]
          const availableSystemVoices = window.speechSynthesis.getVoices();
          const localizedVoiceMatch = availableSystemVoices.find(voice => voice.lang.includes('en'));
          if (localizedVoiceMatch) {
            regenerateWarningUtterance.voice = localizedVoiceMatch;
          }
          
          regenerateWarningUtterance.rate = 1.05;  // Modern, crisp professional alert speed [12]
          regenerateWarningUtterance.pitch = 0.95; // Premium cinematic warning pitch factor [12]
          
          // Dispatch vocal stream natively down to the client machine speakers [12]
          window.speechSynthesis.speak(regenerateWarningUtterance);
          console.log("Parametric Voice Output: Dispatched hardware regeneration restriction alert audio vectors successfully.");
        }
        
        return; // Terminate execution line instantly. No API call or background loading spinner is triggered! [2]
      }


	 // ==========================================================================
      // 🟢 SUCCESS PATHWAY: Only reached if a true user-uploaded image is present
      // ==========================================================================
      
      // If your platform fires a success toast, place it safely HERE behind the guard
      if (typeof showToast === 'function') {
        showToast("Regeneration started...");
      }

      // Lock buttons and start hardware accelerated sync symbol rotation animations
      const syncIconNode = regenerateBtn.querySelector('.material-symbols-outlined');
      regenerateBtn.disabled = true;
      regenerateBtn.style.cursor = "wait";
      if (syncIconNode) syncIconNode.style.animation = "eliteNeonPinkSpin 0.75s linear infinite";

      const fileAsset = fileInput.files[0];
      executeMultimodalGeneration(fileAsset, activeSelectedMode);

      // Automated teardown bindings once fresh audio files finish assembling
      if (hiddenAudioNode) {
        const restoreRegenerateChassisBaseState = () => {
          regenerateBtn.disabled = false;
          regenerateBtn.style.cursor = "pointer";
          if (syncIconNode) syncIconNode.style.animation = "none";
        };
        hiddenAudioNode.addEventListener('canplaythrough', restoreRegenerateChassisBaseState, { once: true });
        setTimeout(restoreRegenerateChassisBaseState, 35000); // Absolute safety timeout protection line
      }
    });
  }


// ==========================================================================
  // 🎨 Step D: Dynamic UI View Rendering State Machine Operators
  // ==========================================================================
  
 function updateStoryPanelToLoadingState() {
  if (uploaderCard) uploaderCard.style.display = 'none';
  
  if (storyWorkspace) {
    storyWorkspace.style.display = 'block';
    
    // 🅰️ Update the primary header layout block to show active calculation state
    const storyHeaderTitle = document.querySelector('.story-head h3');
    if (storyHeaderTitle) {
      storyHeaderTitle.textContent = "GENERATING..."; 
      storyHeaderTitle.style.color = "#00e5ff"; 
      storyHeaderTitle.style.textShadow = "0 0 10px rgba(0, 229, 255, 0.4)";
    }

    // 🎯 Select a random compact quote from the array matrix
    const randomQuoteIndex = Math.floor(Math.random() * MULTIMODAL_AI_THOUGHTS_MATRIX.length);
    const selectedThoughtString = MULTIMODAL_AI_THOUGHTS_MATRIX[randomQuoteIndex];

    // 🅲 Inject your exact requested prompt copy loading text layout
    const storyTextField = document.getElementById('dynamicStoryTextContent');
    if (storyTextField) {
      storyTextField.innerHTML = `
        The response is getting generated. In the meanwhile, read the thought of the day from Picture Alive AI:<br>
        <span class="highlight-cyan" style="display:block; margin:12px 0; padding:10px 14px; background:rgba(0,229,255,0.04); border-left:2px solid #00e5ff; border-radius:4px; font-style:italic; font-size:12.5px; line-height:1.5;">
          ${selectedThoughtString}
        </span>
        Once your response is ready, you will see on this screen that your response is ready to preview. Preview the response in the main screen.
      `;
      storyTextField.style.color = "#d1d1e0";
    }
    
    // ==========================================================================
    // 🎯 THE BADGE CONTENT OVERWRITE FIX:
    // Safely forces the inner text elements to display active processing states!
    // ==========================================================================
    const metaBadge = document.getElementById('dynamicMetaBadge');
    const metaIcon = document.getElementById('dynamicMetaIcon');
    const metaText = document.getElementById('dynamicMetaText');

    if (metaBadge && metaText && metaIcon) {
      // 🎨 Swap standard text to show active generation progress metrics string
      metaText.textContent = "RESPONSE GETTING GENERATED...";
      
      // Swap properties to neutral loading layouts parameters
      metaIcon.textContent = "sync"; // Changes equalizer symbol to an interactive sync symbol arrow loop
      metaIcon.style.animation = "spin 2s linear infinite"; // Forces active hardware acceleration rotation loop
      
      metaBadge.style.borderColor = "rgba(255,255,255,0.1)";
      metaBadge.style.color = "#8a8a9a";
      metaBadge.style.background = "rgba(255,255,255,0.02)";
      metaBadge.style.textShadow = "none";
    }

    // Hide any old active equalizer waveform frequency graphs until data completely returns
    const audioWaveMesh = document.querySelector('.ambient-audio-waveform-mesh');
    if (audioWaveMesh) {
      audioWaveMesh.style.display = "none";
    }
  }
}

  
  // ==========================================================================
// 🟢 THE COMPONENT FIX: Unified Success State Visual & Audio Realignment
// ==========================================================================
function renderStoryPanelSuccessState(mode) {
  const storyHeaderTitle = document.querySelector('.story-head h3');
  const metaBadge = document.querySelector('.narrator-meta-badge');
  const storyTextField = document.getElementById('dynamicStoryTextContent');
  const audioWaveMesh = document.querySelector('.ambient-audio-waveform-mesh');

  // 🅰️ Update the primary header layout block to a glowing cyan success matrix
  if (storyHeaderTitle) {
    storyHeaderTitle.textContent = "GENERATION COMPLETE";
    storyHeaderTitle.style.color = "#00e5ff";
    storyHeaderTitle.style.textShadow = "0 0 10px rgba(0, 229, 255, 0.4)";
  }

  // 🅱️ Unhide and illuminate your energetic cyan streaming status badge
  if (metaBadge) {
    metaBadge.style.display = "inline-flex";
    metaBadge.innerHTML = `<span class="material-symbols-outlined">graphic_eq</span><span>VOICEOVER STREAM READY</span>`;
    metaBadge.style.borderColor = "rgba(0, 229, 255, 0.25)";
    metaBadge.style.color = "#00e5ff";
    metaBadge.style.background = "rgba(0, 229, 255, 0.08)";
    metaBadge.style.textShadow = "0 0 5px rgba(0, 229, 255, 0.4)";
  }

  // 🅲 Inject your premium descriptive marketing text panel content strings [google]
  if (storyTextField) {
    storyTextField.innerHTML = `Response got generated, it is ready in the main panel for you to listen. Do not forget to <span class="highlight-pink">Download</span> & <span class="highlight-pink">Share</span> it. If you want to get a new audio script track for your same picture, click on the <span class="highlight-cyan">Regenerate</span> button.`;
    storyTextField.style.color = "#d1d1e0";
  }

  // 🅳 Make the animated equalizer waveform frequency mesh graph visible [google]
  if (audioWaveMesh) {
    audioWaveMesh.style.display = "flex";
  }

  // 🎯 🆂 THE AUDIO VOICE-OVER ATTACHMENT: Say the success phrase out loud!
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel(); // 💥 Drop any currently playing vocal buffers to prevent overlaps
    
    // Instantiate a hardware vocalization controller stream [google]
    const successUtterance = new SpeechSynthesisUtterance("Response got generated successfully. Preview your response in main screen.");
    
    // Select an official high-fidelity localized English voice module configuration [google]
    const availableSystemVoices = window.speechSynthesis.getVoices();
    const localizedVoiceMatch = availableSystemVoices.find(voice => voice.lang.includes('en'));
    if (localizedVoiceMatch) {
      successUtterance.voice = localizedVoiceMatch;
    }
    
    successUtterance.rate = 1.0;   // Standard natural pacing speed [google]
    successUtterance.pitch = 0.95;  // Premium cinematic narrative tone pitch factor [google]
    
    // Dispatch vocal stream natively down to the client machine speakers [google]
    window.speechSynthesis.speak(successUtterance);
    console.log("🔊 [Text-To-Speech Success]: Dispatched hardware success announcement audio vectors.");
  }
}


 // ==========================================================================
// 🔴 THE COMPONENT FIX: Unified Error State Visual Realignment (Network Fortified)
// ==========================================================================
function renderStoryPanelErrorState(errorMessage) {
  const storyHeaderTitle = document.querySelector('.story-head h3');
  const metaBadge = document.querySelector('.narrator-meta-badge');
  const storyTextField = document.getElementById('dynamicStoryTextContent');
  const audioWaveMesh = document.querySelector('.ambient-audio-waveform-mesh');

  // Convert incoming argument to a clean string format to protect matching checks
  const normalizedErrorText = String(errorMessage || 'Internal Pipeline Stall');

  console.log(`🚨 [Error Renderer Active]: Compiling visual layouts for error trace -> "${normalizedErrorText}"`);

  // 🅰️ Update the primary header layout block to a glowing red warning matrix
  if (storyHeaderTitle) {
    storyHeaderTitle.textContent = "ERROR";
    storyHeaderTitle.style.color = "#ff1744";
    storyHeaderTitle.style.textShadow = "0 0 12px #ff1744";
  }

  // 🅱️ Transform the cyan badge into a matching red error frame track!
  if (metaBadge) {
    metaBadge.style.display = "inline-flex";
    metaBadge.innerHTML = `<span class="material-symbols-outlined" style="color:#ff1744;">gpp_bad</span><span>RESPONSE GENERATION FAILED</span>`;
    metaBadge.style.borderColor = "rgba(255, 23, 68, 0.35)";
    metaBadge.style.color = "#ff1744";
    metaBadge.style.background = "rgba(255, 23, 68, 0.08)";
    metaBadge.style.textShadow = "0 0 5px rgba(255, 23, 68, 0.4)";
  }

  // 🅲 THE CRITICAL CONTENT FIX: Enforce your exact requested system diagnostic text string
  if (storyTextField) {
    // Forcefully wipe out any cached old success panel text content blocks completely
    storyTextField.innerHTML = `Response not generated, please try again. If the issue still exists, contact our support team <a href="#" class="cyber-support-anchor-link" style="color:#ff007f; font-weight:700; text-decoration:underline; text-shadow:0 0 6px rgba(255,0,127,0.4);">Support</a>. <br><br><small style="color:rgba(255,255,255,0.25); font-family:monospace; font-size:10px;">Diagnostic code trace parameters: ${normalizedErrorText}</small>`;
    storyTextField.style.color = "#a2a2b0";
  }

  // 🅳 Hide the equalizer animation graph track completely since no sound file compiled successfully
  if (audioWaveMesh) {
    audioWaveMesh.style.display = "none";
  }

  // 🎯 THE AUDIO VOICE-OVER ATTACHMENT
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel(); // Drop any currently playing vocal buffers to prevent overlaps
    
    // Instantiate a hardware vocalization controller stream
    const failureUtterance = new SpeechSynthesisUtterance("Response generation failed.");
    
    const availableSystemVoices = window.speechSynthesis.getVoices();
    const localizedVoiceMatch = availableSystemVoices.find(voice => voice.lang.includes('en'));
    if (localizedVoiceMatch) {
      failureUtterance.voice = localizedVoiceMatch;
    }
    
    failureUtterance.rate = 1.0;  
    failureUtterance.pitch = 0.95; 
    
    window.speechSynthesis.speak(failureUtterance);
    console.log("🔊 [Text-To-Speech Fallback]: Dispatched hardware exception announcement audio vectors.");
  }
}

	// ==========================================================================
// 🔊 PICTURE ALIVE AI LAB WORKSPACE SYSTEM CONTROLLER (With Voice Greeting)
// ==========================================================================
window.executeLabWorkspaceWelcome = function(event) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }

  console.log("🛸 [AI Lab Router]: Transitioning layout frameworks back to primary workspace dashboard...");

  // 1. SELECT WORKSPACE OBJECT PANELS
  const storyWorkspace = document.getElementById('storyOutputStateWorkspace');
  const uploaderCard = document.getElementById('uploaderStateWorkspace');
  const hiddenAudioNode = document.getElementById('hiddenPreviewAudio');

  // Clear out old active media parameters to prepare the canvas fresh
  if (hiddenAudioNode) {
    hiddenAudioNode.pause();
    hiddenAudioNode.src = "";
  }

  // 🔄 Swaps active panel visibility to slide the user back to input screens smoothly
  if (storyWorkspace) storyWorkspace.style.display = "none";
  if (uploaderCard) uploaderCard.style.display = "block";

  // 🎯 🆂 THE AUDIO LAB WELCOME FIX: Instruct the browser to speak your exact phrases out loud! [12]
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel(); // 💥 Instantly drop old vocal queues to block overlapping sound traces
    
    // 📝 Compile your exact multi-phrase request string
    const welcomeLabGreetingPhrase = `
										Welcome to Picture Alive AI LAB

										BEYOND IMAGINATION

										Where Artificial Intelligence Transcends Perception and Every Image Evolves into an Extraordinary Digital Experience.

										Embark upon a revolutionary journey powered by next-generation Multimodal Artificial Intelligence, where static imagery is meticulously transformed into immersive narratives, context-aware intelligence, lifelike voice narration, cinematic storytelling, and profound knowledge discovery.

										Picture Alive AI - Transform a single image into a multidimensional repository of contextual intelligence, historical interpretation - Audio Guide, accessibility assistance, educational exploration, immersive narration, digital product analysis, wildlife recognition, and cinematic storytelling—redefining how humanity perceives, 
										understands, and interacts with the visual world by empowering every photograph to communicate, educate, inspire, and captivate beyond the boundaries of imagination.
										`;

    const labUtterance = new SpeechSynthesisUtterance(welcomeLabGreetingPhrase);
    
    // Auto-select a high-fidelity natural English voice module from backend hardware
    const availableSystemVoices = window.speechSynthesis.getVoices();
    const premiumVoiceMatch = availableSystemVoices.find(voice => voice.lang.includes('en'));
    if (premiumVoiceMatch) {
      labUtterance.voice = premiumVoiceMatch;
    }
    
    labUtterance.rate = 0.98;   // Smooth, sophisticated scientific narrative speed profile [12]
    labUtterance.pitch = 1.0;   // Clean crystal pitch frequencies [12]
    
    // Stream parameters down to client machine speaker channels
    window.speechSynthesis.speak(labUtterance);
    console.log("🔊 [Lab Voice Engine]: Dispatched hardware workspace welcome sequence announcement vectors.");
  } else {
    if (typeof triggerPremiumSystemToast === 'function') {
      triggerPremiumSystemToast("Returned to Picture Alive AI Lab Workspace.");
    }
  }
};

// Warm up system speech engines on document bootstrap
if ('speechSynthesis' in window) { window.speechSynthesis.getVoices(); }


// ==========================================================================
// 🔊 PREMIUM UPGRADE CONTROLLER ENGINE (Instant Hardware Vocalization Loop)
// ==========================================================================
window.executeProUpgradeSequence = function(event) {
  if (event) {
    event.preventDefault();
    event.stopPropagation(); // Forces internal mock frameworks to drop processing hooks completely
  }

  console.log("🛸 [AI Workspace Deck]: Pro Upgrade node initialized by client click handler.");

  // Trigger our custom web application system toast notification if available
  if (typeof triggerPremiumSystemToast === 'function') {
    triggerPremiumSystemToast("Unlocking Premium Processing Pipelines... Shifting to Pro Mode.");
  }

  // 🎯 🆂 THE AUDIO VOICE-OVER EXTRACTION: Instruct the browser to say "Upgrade to Pro" out loud!
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel(); // 💥 Instantly drop playing vocal buffers to prevent overlaps
    
    // Instantiate a hardware vocalization controller stream
    const upgradeUtterance = new SpeechSynthesisUtterance("Upgrade to pro.");
    
    // Auto-select a high-fidelity natural English voice module configuration from backend architecture
    const availableSystemVoices = window.speechSynthesis.getVoices();
    const premiumVoiceMatch = availableSystemVoices.find(voice => voice.lang.includes('en'));
    if (premiumVoiceMatch) {
      upgradeUtterance.voice = premiumVoiceMatch;
    }
    
    upgradeUtterance.rate = 1.05;  // Modern, crisp authoritative pacing speed profile
    upgradeUtterance.pitch = 0.95; // Premium cinematic narrative tone pitch factor
    
    // Dispatch vocal stream natively down to the client machine speakers
    window.speechSynthesis.speak(upgradeUtterance);
    console.log("A.I. Voice Engine: Dispatched hardware upgrade announcement audio vectors successfully.");
  } else {
    console.warn("Speech synthesis interface is restricted or blocked inside this browser environment layout.");
  }
};

// Warm up system speech engines on document bootstrap
if ('speechSynthesis' in window) { window.speechSynthesis.getVoices(); 
}


  
  function processSelectedFileAsset(file) {
    // 1. File Type Validation Shield
	  if (!file.type.startsWith('image/')) {
	    showToast("Invalid selection. Please upload a supported image file (.jpg, .png, .webp).");
	    return;
	  }
  
	  // 🎯 2. THE FIX: Strict 20MB File Size Validation Guard
	  // 20MB calculated exactly in bytes: 20 * 1024 * 1024 = 20971520 bytes
	  const MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024; 
	  
	  if (file.size > MAX_FILE_SIZE_BYTES) {
	    // Blocks execution instantly and displays an explicit error message
	    showToast(`File is too large! Maximum limit is 20MB. Your file: ${(file.size / 1024 / 1024).toFixed(2)}MB`);
	    
	    // Clear out target paths to reset uploader state configurations safely
	    targetUploadedFile = null;
	    generateBtn.setAttribute('disabled', 'true');
	    fileInput.value = ""; 
	    return;
	  }
    
    targetUploadedFile = file;
    console.log(`📂 [Asset Loaded]: ${file.name} (Size: ${(file.size / 1024 / 1024).toFixed(2)} MB)`);
    
    // Dynamically unlock the main AI generation trigger button matrix
    generateBtn.removeAttribute('disabled');
    document.querySelector('.primary-drag-text').textContent = `Selected: ${file.name}`;
  }


  // 5. Revert View Workspace State Switching Controller
  revertBtn.addEventListener('click', () => {
    isStoryGenerated = false;
    targetUploadedFile = null;
    document.querySelector('.primary-drag-text').textContent = "Drag & Drop your image here";
    generateBtn.setAttribute('disabled', 'true');
    fileInput.value = ""; // Reset hidden file paths safely
    evaluateActiveViewState();
  });
  
  // 🔄 Verification Controller Render Engine Toggle Loop
  function evaluateActiveViewState() {
    if (isStoryGenerated) {
      uploaderWorkspace.style.display = 'none';
      storyWorkspace.style.display = 'block';
    } else {
      storyWorkspace.style.display = 'none';
      uploaderWorkspace.style.display = 'block';
    }
  }

  
  
  // 1. Initialize Default State (Loads Education natively on startup)
  loadCategoryWorkspace('heritage_tourism');
  
  // 2. Tab Selection Click Listener
  menuTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      // Extract data-output value attribute key string (e.g. "education", "digital_world")
      const targetCategory = tab.dataset.output;
      activeSelectedMode = tab.dataset.output;
      
      console.log(`🎯 [Mode Context Shift]: System operations mapped to: "${activeSelectedMode}"`);

      
       if (targetCategory && categoryMediaAssets[targetCategory]) {
        // Toggle structural active visibility aura states on navigation list links
        menuTabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        loadCategoryWorkspace(targetCategory);
        // Reset playback controls to prevent track cross-bleeding
        resetAudioPreviewCanvas();
      }
    });
  });
  
  // 2. Intercept image upload, swap preview canvas layout instantly, then run API calls
  if (fileInput) {
    fileInput.addEventListener('change', (event) => {
      const selectedFile = event.target.files[0];
      if (!selectedFile) return;

      // 📏 Client-side 20MB payload safeguard validation parameters check
      if (selectedFile.size > 20 * 1024 * 1024) {
        if (typeof showToast === 'function') {
        showToast(`File is too large! Maximum limit is 20MB. Your file: ${(selectedFile.size / 1024 / 1024).toFixed(2)}MB`);
        }
        fileInput.value = ""; 
        return;
      }

	  isUserCustomUploadStaged = true; 
      // Lock file into memory placeholder
      targetUploadedFileBlob = selectedFile;
      console.log(`📂 [Asset Staged]: ${selectedFile.name} ready for explicit click generation command.`);


      console.log(`📂 [Image Captured]: Rendering "${selectedFile.name}" instantly to main viewer card...`);

      // 🎯 STEP 1: Instant Viewer Update. Convert local file block into an active view path link
      const temporaryObjectUrl = URL.createObjectURL(selectedFile);
      if (mainPreviewImg) {
        mainPreviewImg.src = temporaryObjectUrl;
      }

      // Hide uploader workspace state panels automatically
      const uploaderCard = document.getElementById('uploaderStateWorkspace');
      if (uploaderCard) uploaderCard.style.display = 'block';

     // 🛑 THE FIX: Keep uploader visible, display filename text, and UNLOCK generate button
      const dragText = document.querySelector('.primary-drag-text');
      if (dragText) dragText.textContent = `Ready: ${selectedFile.name}`;
      
      if (generateBtn) generateBtn.removeAttribute('disabled');
    });
  }

 // 🎯 2. EXPLICIT USER CLICK TRIGGER ACTION PIPELINE
  if (generateBtn) {
    generateBtn.addEventListener('click', (e) => {
      e.preventDefault();
      
      if (!targetUploadedFileBlob) {
        if (typeof showToast === 'function') showToast("Please select or drop an image asset first.");
        return;
      }

      // Fire processing transaction loops
      executeMultimodalGeneration(targetUploadedFileBlob, activeSelectedMode);
    });
  }

// 📡 3. UNIFIED API CALL WITH INTEGRATED LOADING STATES
  function executeMultimodalGeneration(fileAsset, targetMode) {
    console.log("🚀 [API Handshake]: User triggered Generation. Initializing UI loading configurations...");

	  updateStoryPanelToLoadingState();
    // ⏳ STEP A: Enforce Busy Cursor and Loading Indicators globally
    document.body.style.cursor = "wait"; 
    if (generateBtn) {
      generateBtn.disabled = true;
      generateBtn.innerHTML = `<span class="material-symbols-outlined" style="animation: spin 1s linear infinite;">sync</span> SYSTEM GENERATING...`;
    }
    
     // 🎯 THE ARRAY ISOLATION SAFETY GUARD:
  // If fileAsset is still wrapped inside a FileList container, extract index 0
  const cleanBinaryFile = (fileAsset instanceof FileList) ? fileAsset[0] : fileAsset;

  // 🎯 THE MULTI-PART PACKAGING FIX:
  // Construct a fresh FormData instance and map the key 'image' to match your FastAPI parameter exactly
  const payloadContainer = new FormData();
  payloadContainer.append('image', cleanBinaryFile);  

    // 🎯 THE ABSOLUTE RELATIVE PATH FIX: Built using explicit string concatenation to avoid syntax bugs
  // This constructs EXACTLY: "api/modes/heritage_tourism/generate" (relative to your active port)
   const apiEndpointUrl = "http://127.0.0.1:8000" +"/api/modes/" + targetMode + "/generate";
 console.log("📡 [Outbound Request]: Target Path verified -> " + apiEndpointUrl);

  // ==========================================================================
  // 🔍 THE INSPECTION LOOP: Read exactly what is being sent inside the payload
  // ==========================================================================
  console.log("📊 [Payload Debugger]: Opening FormData internal keys configuration layout...");
  for (let [key, value] of payloadContainer.entries()) {
    if (value instanceof File) {
      console.log(`✅ Form Key: "${key}" -> File Name: "${value.name}" | Size: ${(value.size / 1024 / 1024).toFixed(2)} MB | Type: "${value.type}"`);
    } else {
      console.log(`✅ Form Key: "${key}" -> Content Value: "${value}"`);
    }
  }


    fetch(apiEndpointUrl, {
      method: 'POST',
      body: payloadContainer
    })
    .then(response => {
      if (!response.ok) throw new Error(`HTTP transaction stall. Status returned: ${response.status}`);
		 // Capture original filename string token indicators out of headers safely
      const contentDisposition = response.headers.get('Content-Disposition');
      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/i);
        if (filenameMatch && filenameMatch[1]) {
          lastGeneratedFilename = filenameMatch[1]; 
          console.log(`🏷️ [System Network Sync]: Cached backend file pointer reference -> "${lastGeneratedFilename}"`);
        }
      }
	
      return response.blob(); 
    })
    .then(audioBlobData => {
      console.log("✅ [API Process Success]: Binary sound vectors unpacked safely.");

	  // ==========================================================================
      // 🎯 THE GENIUS CACHE FIX: Lock the raw binary blob into memory right now!
      // ==========================================================================
      successfullyCompiledAudioBlobCache = audioBlobData; 
      
      // Mount path elements to baseline players
      const activeAudioTrackBlobUrl = URL.createObjectURL(audioBlobData);
      if (hiddenAudioNode) {
        hiddenAudioNode.src = activeAudioTrackBlobUrl;
        hiddenAudioNode.load();
      }
      renderStoryPanelSuccessState(targetMode);
		
    })
    .catch(err => {
      console.error("❌ [API Processing Failed]:", err);
		
      successfullyCompiledAudioBlobCache = null;
      lastGeneratedFilename = null;
      
       if (hiddenAudioNode) { hiddenAudioNode.src = ""; }
       const finalErrorStringText = err.message || String(err);
      renderStoryPanelErrorState(finalErrorStringText);
      
    })
    .finally(() => {
      // 🛑 STEP B: Complete Processing Lifecycle. Restore default cursor and buttons layout metrics
      document.body.style.cursor = "default";
      if (generateBtn) {
        generateBtn.innerHTML = `<span class="material-symbols-outlined">bolt</span> GENERATE AI STORY`;
        // Keep enabled if error occurs so users can try clicking again cleanly
        if (!storyWorkspace || storyWorkspace.style.display === 'none') {
          generateBtn.removeAttribute('disabled');
        }
      }
    });
  }


 // ==========================================================================
  // 🎮 4. INTEGRATED PLAYER CONTROLLER LOGIC LOOP HOOKS (Standard Play/Pause Click Toggles)
  // ==========================================================================
  if (playPreviewBtn && hiddenAudioNode) {
    playPreviewBtn.addEventListener('click', (e) => {
      e.preventDefault();
      
      if (!hiddenAudioNode.src || hiddenAudioNode.src === "" || !isUserCustomUploadStaged ) {
        if (typeof showToast === 'function') {
          showToast("Please upload an image asset first to compile an active audio guide track.");
        }
        return;
      }
      
      // 🎯 THE SCOPING FIX: Replaced broken 'this' with 'playPreviewBtn' inside your arrow function scope
      const activeIconSpanNode = playPreviewBtn.querySelector('.material-symbols-outlined');

      // Sync the tracking state variables natively with the true media state engine
      previewAnimating = hiddenAudioNode.paused; 
      
      // Clear out any stale text strings inside your active toast system if applicable
      if (typeof clearAllActiveToasts === 'function') {
        clearAllActiveToasts();
      }

      if (hiddenAudioNode.paused) {
        console.log("📡 [Media Event Request]: Dispatched play action call...");
        
        // 📈 Trigger on-screen layout progress animations exactly as requested
        playPreviewBtn.classList.add('playing');
        if (scrubberFill) scrubberFill.style.width = '75%';
        
        // 📱 Fire your custom operational status notification toast string onto your viewport
        if (typeof showToast === 'function') {
          showToast('Preview playing');
        } else if (typeof triggerPremiumSystemToast === 'function') {
          triggerPremiumSystemToast('Preview playing');
        }

        // 🎯 🆂 THE AUDIO VOICE-OVER ATTACHMENT: Updated with the clean speech phrase
        if ('speechSynthesis' in window) {
          window.speechSynthesis.cancel(); // Drop any current vocal streams to block overlaps
          
          const playUtterance = new SpeechSynthesisUtterance("Preview playing.");
          const availableSystemVoices = window.speechSynthesis.getVoices();
          const localizedVoiceMatch = availableSystemVoices.find(voice => voice.lang.includes('en'));
          if (localizedVoiceMatch) playUtterance.voice = localizedVoiceMatch;
          
          playUtterance.rate = 1.05;  // Modern, crisp professional informative speed profile
          playUtterance.pitch = 1.0;   // Neutral digital confirmation pitch frequency
          window.speechSynthesis.speak(playUtterance);
        }

        hiddenAudioNode.play()
          .then(() => {
            if (activeIconSpanNode) activeIconSpanNode.textContent = "pause";
          })
          .catch(err => console.error("Playback interrupted:", err));

      } else {
        console.log("📡 [Media Event Request]: Dispatched pause action call...");
        
        // 📉 Trigger on-screen layout progress animations exactly as requested
        playPreviewBtn.classList.remove('playing');
        if (scrubberFill) scrubberFill.style.width = '45%';
        
        // 📱 Fire your custom operational status notification toast string onto your viewport
        if (typeof showToast === 'function') {
          showToast('Preview paused');
        } else if (typeof triggerPremiumSystemToast === 'function') {
          triggerPremiumSystemToast('Preview paused');
        }

        // 🎯 🆂 THE AUDIO VOICE-OVER ATTACHMENT: Updated with the clean speech phrase
        if ('speechSynthesis' in window) {
          window.speechSynthesis.cancel(); // Drop any current vocal streams to block overlaps
          
          const pauseUtterance = new SpeechSynthesisUtterance("Preview paused.");
          const availableSystemVoices = window.speechSynthesis.getVoices();
          const localizedVoiceMatch = availableSystemVoices.find(voice => voice.lang.includes('en'));
          if (localizedVoiceMatch) pauseUtterance.voice = localizedVoiceMatch;
          
          pauseUtterance.rate = 1.05;
          pauseUtterance.pitch = 1.0;
          window.speechSynthesis.speak(pauseUtterance);
        }

        hiddenAudioNode.pause();
        if (activeIconSpanNode) activeIconSpanNode.textContent = "play_arrow";
      }
    });
   
    // ==========================================================================
    // 🎯 BACKUP STATE LISTENERS: Keeps icons synced if audio ends or clips
    // ==========================================================================
    hiddenAudioNode.addEventListener('play', () => {
      const activeIconSpanNode = playPreviewBtn.querySelector('.material-symbols-outlined');
      if (activeIconSpanNode) activeIconSpanNode.textContent = "pause";
      playPreviewBtn.classList.add('playing');
      previewAnimating = true;
    });

    hiddenAudioNode.addEventListener('pause', () => {
      const activeIconSpanNode = playPreviewBtn.querySelector('.material-symbols-outlined');
      if (activeIconSpanNode) activeIconSpanNode.textContent = "play_arrow";
      playPreviewBtn.classList.remove('playing');
      previewAnimating = false;
    });
	    
    // 5. Scrubber timeline tracking bar moving update parameters animation loops
    hiddenAudioNode.addEventListener('timeupdate', () => {
      if (hiddenAudioNode.duration && scrubberFill) {
        const currentProgressPosition = (hiddenAudioNode.currentTime / hiddenAudioNode.duration) * 100;
        scrubberFill.style.width = `${currentProgressPosition}%`;
      }
    });

    // Handle audio loop finishing bounds reset triggers cleanly
    hiddenAudioNode.addEventListener('ended', () => {
      const activeIconSpanNode = playPreviewBtn.querySelector('.material-symbols-outlined');
      if (activeIconSpanNode) activeIconSpanNode.textContent = "play_arrow";
      if (scrubberFill) scrubberFill.style.width = '0%';
      playPreviewBtn.classList.remove('playing');
      previewAnimating = false;
      console.log("🏁 [Media Stream Complete]: UI tracking loops reset.");
    });
  }

  // 6. Interactive timeline track clicking logic (Enables jumping to specific sections of the MP3 file)
  if (scrubberTrack && hiddenAudioNode) {
    scrubberTrack.addEventListener('click', (event) => {
      if (!hiddenAudioNode.src || !hiddenAudioNode.duration) return;

      // Extract horizontal alignment pixel parameters relative to track bounding box shapes
      const timelineRectBounds = scrubberTrack.getBoundingClientRect();
      const clickCoordinateX = event.clientX - timelineRectBounds.left;
      const clickedPercentageRatio = clickCoordinateX / timelineRectBounds.width;

      // Convert ratio straight to timeline second frames indices metrics
      hiddenAudioNode.currentTime = clickedPercentageRatio * hiddenAudioNode.duration;
      console.log(`🎯 [Timeline Scrub]: Audio track skip executed to: ${(hiddenAudioNode.currentTime).toFixed(1)}s`);
    });
  }

  // Clean layout helper parameters
  function resetAudioPreviewCanvas() {
    if (hiddenAudioNode) {
      hiddenAudioNode.pause();
      hiddenAudioNode.src = "";
    }
    if (mainPlayIcon) mainPlayIcon.textContent = "play_arrow";
    if (scrubberFill) scrubberFill.style.width = '0%';
	lastGeneratedFilename = null;
    successfullyCompiledAudioBlobCache = null;
  }

  
   // 3. Render Engine Workspace Loader
  function loadCategoryWorkspace(categoryKey) {
    const dataPack = categoryMediaAssets[categoryKey];
     if (!dataPack) return;

    // 🎯 DEFENSIVE FIX: Guard content assignments with explicit element existence checks
    if (mainPreviewImg){
		
    	mainPreviewImg.src = dataPack.mainPreview;
    	 /* 🎯 THE FIX: Wait for the image file to load, then match the container height to it perfectly */
    mainPreviewImg.onload = function() {
      const container = document.querySelector('.preview-stage');
      if (container) {
        // Reads the physical width and height dimensions of the current image file
        const imageWidth = mainPreviewImg.naturalWidth;
        const imageHeight = mainPreviewImg.naturalHeight;
        
        // Sets the aspect ratio dynamically via CSS style injection
        container.style.aspectRatio = `${imageWidth} / ${imageHeight}`;
        container.style.height = 'auto'; // Release any fixed heights
      }
    };
  }
  
  
    
    // This element assignment was causing your crash due to a missing/mismatched ID selector tag
    if (categoryBadge) {
      categoryBadge.textContent = dataPack.badgeText;
    } else {
      console.warn("⚠️ Warning: Element '#categoryBadge' was not located in your current HTML file.");
    }


     if (scrubberFill) scrubberFill.style.width = '0%';
    if (!thumbnailRow) return;

    // Clear previous elements inside thumbnail track node row
    thumbnailRow.innerHTML = '';

    // Loop data matrices to construct interactive image thumbnails dynamically
    dataPack.thumbnails.forEach((thumbSrc, index) => {
      const thumbWrap = document.createElement('div');
      thumbWrap.className = `thumb ${index === 0 ? 'active' : ''}`; // Lock baseline active class onto first image card
      
      const imgNode = document.createElement('img');
      imgNode.src = thumbSrc;
      imgNode.alt = `${categoryKey} thumbnail option ${index + 1}`;

      // Click to Swap Preview: Tapping a small thumbnail loads it into main preview space immediately
      thumbWrap.addEventListener('click', () => {
        // Toggle active border styling flags across elements
        thumbnailRow.querySelectorAll('.thumb').forEach(t => t.classList.remove('active'));
        thumbWrap.classList.add('active');
        
        // Push thumb source link path to main viewport screen
        mainPreviewImg.src = thumbSrc;
      });

      // Assemble nodes
      thumbWrap.appendChild(imgNode);
      thumbnailRow.appendChild(thumbWrap);
    });
  }

   // 1. Core Routine: Listen if this specific tab context is the popup window returning data
  handleIncomingOAuthCallback();
  
  // 2. Active Session Monitor
  if (localStorage.getItem('user_authenticated') === 'true') {
    const cachedUrl = localStorage.getItem('user_avatar_url');
    updateUIAfterAuth(cachedUrl);
  }

// Bind the login click engine directly onto your custom transparent overlay layer
  const authOverlay = document.getElementById('googleAuthOverlay');
  if (authOverlay) {
    authOverlay.addEventListener('click', launchGoogleLoginWindow);
  }

  // Bind the logout interaction event listener
  const logoutBtn = document.getElementById('uiLogoutTrigger');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', handleUserSignOut);
  }
  
  navItems.forEach((item) => {
    item.addEventListener('click', () => {
      navItems.forEach((nav) => nav.classList.remove('active'));
      item.classList.add('active');
      const labelSpanNode = item.querySelector('span:not(.material-symbols-outlined)');
      let cleanModeLabelName = "Default";
      
      if (labelSpanNode) {
        cleanModeLabelName = labelSpanNode.textContent.trim().toUpperCase();
      } else {
        // Fallback: If no child text span exists, strip out icon strings manually
        cleanModeLabelName = item.textContent.replace(/[a-z_]+/g, '').trim().toUpperCase();
      }

      // 🎯 THE PREMIUM TOAST STRINGS CONVENTION FIX:
      // Formats exactly: "EDUCATION MODE :: Pipeline Activated" or "HERITAGE TOURISM MODE :: Pipeline Activated"
      const premiumToastMessageText = `${cleanModeLabelName} MODE :: Pipeline Activated`;

      console.log(`📡 [Workspace Navigation Sync]: Switching user interface framework parameters to -> "${cleanModeLabelName}"`);

      // Clear out any stale text strings inside your active toast system if applicable
      if (typeof clearAllActiveToasts === 'function') {
        clearAllActiveToasts();
      }

      // 📱 Display the premium workspace navigation confirmation toast notification
      if (typeof showToast === 'function') {
        showToast(premiumToastMessageText);
      } else if (typeof triggerPremiumSystemToast === 'function') {
        triggerPremiumSystemToast(premiumToastMessageText);
      }

      // 🎯 🆂 THE NAVIGATION AUDITORY ATTACHMENT: Say it out loud dynamically!
      if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel(); // Drop any current vocal streams to block overlaps

        // Compiles smoothly: "Switched to Education mode." or "Switched to Heritage Tourism mode."
        const beautifullySpokenLabel = cleanModeLabelName.toLowerCase();
        const navSpokenUtterance = new SpeechSynthesisUtterance(`Switched to ${beautifullySpokenLabel} mode.`);
        
        const availableSystemVoices = window.speechSynthesis.getVoices();
        const localizedVoiceMatch = availableSystemVoices.find(voice => voice.lang.includes('en'));
        if (localizedVoiceMatch) {
          navSpokenUtterance.voice = localizedVoiceMatch;
        }
        
        navSpokenUtterance.rate = 1.05;  // Modern, crisp professional informative speed profile
        navSpokenUtterance.pitch = 1.0;   // Neutral digital confirmation pitch frequency
        
        window.speechSynthesis.speak(navSpokenUtterance);
        console.log(`🔊 [Text-To-Speech Nav Sync]: Dispatched hardware announcement tracks for: "${cleanModeLabelName}"`);
      }
    });
  });

  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((btn) => btn.classList.remove('active'));
      tab.classList.add('active');
      const currentMode = tab.dataset.output.toUpperCase();
		// ==========================================================================
      // 🔒 CONTEXT GUARD ROUTINE: Block Pro modes with matching audio feedback
      // ==========================================================================
      if (currentMode !== "AUDIO") {
        // Formats your mode tag text string nicely for public presentation (e.g., "HERITAGE TOURISM")
        const dynamicModeLabel = currentMode.replace(/_/g, " ").toUpperCase();
        const proValidationBlockText = `${dynamicModeLabel} mode, Upgrade to PRO`;
        
        console.warn(`⚠️ [Feature Blocked]: Restricted access for mode -> "${dynamicModeLabel}". Firing visual and vocal alerts.`);

        // Clear out any stale text strings inside your active toast system if applicable
        if (typeof clearAllActiveToasts === 'function') {
          clearAllActiveToasts();
        }

        // 📱 Fire your custom alert notice strings onto your screen layout viewport
        if (typeof showToast === 'function') {
          showToast(proValidationBlockText);
        } else if (typeof triggerPremiumSystemToast === 'function') {
          triggerPremiumSystemToast(proValidationBlockText);
        } else {
          alert(proValidationBlockText);
        }

        // 🎯 🆂 THE AUDIO VOICE-OVER ATTACHMENT: Say the warning phrase out loud!
        if ('speechSynthesis' in window) {
          window.speechSynthesis.cancel(); // 💥 Drop any currently playing vocal buffers to prevent overlaps
          
          // Instantiate a hardware vocalization controller stream with your exact requested warning phrase layout
          const proUpgradeUtterance = new SpeechSynthesisUtterance(`${dynamicModeLabel} mode, Upgrade to Pro.`);
          
          // Select an official high-fidelity localized English voice module configuration
          const availableSystemVoices = window.speechSynthesis.getVoices();
          const localizedVoiceMatch = availableSystemVoices.find(voice => voice.lang.includes('en'));
          if (localizedVoiceMatch) {
            proUpgradeUtterance.voice = localizedVoiceMatch;
          }
          
          proUpgradeUtterance.rate = 1.05;  // Modern, crisp professional alert speed profile
          proUpgradeUtterance.pitch = 0.95; // Premium cinematic warning pitch factor
          
          // Dispatch vocal stream natively down to the client machine speakers
          window.speechSynthesis.speak(proUpgradeUtterance);
          console.log("Parametric Voice Output: Dispatched hardware premium restriction alert audio vectors successfully.");
        }
        
        return; // Terminate execution line instantly. No API call or background loading spinner is triggered!
      }
    });
  });

  document.querySelectorAll('[data-action]').forEach((button) => {
    button.addEventListener('click', () => {
      const action = button.dataset.action;
       // ==========================================================================
      // 🔒 ACTION INTERCEPTOR MATRIX: Handles Pro Restrictions and Started Metrics
      // ==========================================================================
      if (action && (action.toLowerCase() === "convert" || action.toLowerCase() === "edit")) {
        // Format the action name string cleanly (e.g., "Convert" or "Edit")
        const capitalizedAction = action.charAt(0).toUpperCase() + action.slice(1);
        const proActionValidationText = `${capitalizedAction}:: Upgrade to PRO`;
        
        console.warn(`⚠️ [Action Blocked]: Restricted tool context -> "${capitalizedAction}". Firing Pro restriction alerts.`);

        // Clear out any stale text strings inside your active toast system if applicable
        if (typeof clearAllActiveToasts === 'function') {
          clearAllActiveToasts();
        }

        // 📱 Display Pro validation toast notification
        if (typeof showToast === 'function') {
          showToast(proActionValidationText);
        } else if (typeof triggerPremiumSystemToast === 'function') {
          triggerPremiumSystemToast(proActionValidationText);
        }

        // 🎯 🆂 THE PRO AUDIO VOICE-OVER ATTACHMENT: Say "Upgrade to Pro" out loud!
        if ('speechSynthesis' in window) {
          window.speechSynthesis.cancel(); // Drop any current vocal streams to block overlaps
          
          const proActionUtterance = new SpeechSynthesisUtterance(`${capitalizedAction}. Upgrade to Pro.`);
          const availableSystemVoices = window.speechSynthesis.getVoices();
          const localizedVoiceMatch = availableSystemVoices.find(voice => voice.lang.includes('en'));
          if (localizedVoiceMatch) proActionUtterance.voice = localizedVoiceMatch;
          
          proActionUtterance.rate = 1.05;
          proActionUtterance.pitch = 0.95;
          window.speechSynthesis.speak(proActionUtterance);
        }
        
        return; // Safe exit out of the restricted workflow track
		  } else {
         showToast(`${action.charAt(0).toUpperCase() + action.slice(1)} started`);
      }
    });
  });

  document.querySelector('.btn-upgrade').addEventListener('click', () => {
    showToast('Upgrade flow opened');
  });


  if (helpBtn) {
    helpBtn.addEventListener('click', (event) => {
      // Prevent any parent links or bubble events from disrupting the script
      event.preventDefault();

      const emailTo = 'poppenspeladvies@gmail.com';
      const subjectText = 'Support Request - PICTURE ALIVE AI';
      const mailtoUrl = `mailto:${emailTo}?subject=${encodeURIComponent(subjectText)}`;
      
      // 🛠️ The Working Frame Isolation Engine
      let mailFrame = document.getElementById('hiddenMailFrame');
      if (!mailFrame) {
        mailFrame = document.createElement('iframe');
        mailFrame.id = 'hiddenMailFrame';
        mailFrame.style.display = 'none';
        document.body.appendChild(mailFrame);
      }
      
      // Inject the URL string into the frame sandbox to launch the window safely
      mailFrame.src = mailtoUrl;
     // console.log("✅ Frame-isolated email window triggered successfully.");
      showToast(`Email to Picture Alive AI Support Team`);
    });
  }
  
});

// Directly launches the secure, popup account consent screen using clean web protocols
function launchGoogleLoginWindow() {
  if (localStorage.getItem('user_authenticated') === 'true') {
    return;
  }

  // 🛠️ Force the redirect URI to be clean and explicit (Removes file endpoints that confuse popups)
  const redirectUri = window.location.origin + window.location.pathname;

// 🎯 FIXED: Changed 'google.com' to 'accounts.google.com' and corrected the scope format
  const oauthUrl =
    "https://accounts.google.com/o/oauth2/v2/auth?" +
    "client_id=" + encodeURIComponent(GOOGLE_CLIENT_ID) +
    "&redirect_uri=" + encodeURIComponent(redirectUri) +
    "&response_type=token" +
    "&scope=" + encodeURIComponent("openid email profile") +
    "&include_granted_scopes=true" +
    "&prompt=select_account" +
    "&state=picture_alive_auth";             

  const width = 500, height = 650;
  const left = (window.screen.width / 2) - (width / 2);
  const top = (window.screen.height / 2) - (height / 2);

  // 🚪 Cross-Window Interceptor: Listen for cross-communication messages from our own popup
  window.removeEventListener('message', handlePopupMessage); // Clean old listeners
  window.addEventListener('message', handlePopupMessage);

  window.open(
    oauthUrl, 
    "GoogleSignInPopup", 
    `width=${width},height=${height},top=${top},left=${left},toolbar=no,menubar=no,scrollbars=yes,status=no`
  );
}

// 🌐 This logic executes inside the popup window context when Google redirects back to your redirectUri
function handleIncomingOAuthCallback() {
  const urlHash = window.location.hash;
  
  // Check if this window was opened as a popup and contains the login tokens
  if (urlHash && urlHash.includes("access_token") && window.opener) {
    
    // Send the hash string straight up to the parent window background application
    window.opener.postMessage({ type: "OAUTH_HASH", hash: urlHash }, window.location.origin);
    
    // 💥 Kill the popup window immediately!
    window.close();
  }
}

// 📥 The main website receives this data packet from the closing popup window
function handlePopupMessage(event) {
  // Security baseline verification check
  if (event.origin !== window.location.origin) return;

  if (event.data && event.data.type === "OAUTH_HASH") {
    const params = new URLSearchParams(event.data.hash.replace("#", "?"));
    const accessToken = params.get("access_token");

    if (accessToken) {
      fetch(`https://www.googleapis.com/oauth2/v3/userinfo`, {
        headers: { 'Authorization': `Bearer ${accessToken}` }
      })
      .then(response => response.json())
      .then(data => {
        if (data && data.picture) {
          localStorage.setItem('user_authenticated', 'true');
          localStorage.setItem('user_avatar_url', data.picture);
          
          // Re-render layout frames immediately on screen
          updateUIAfterAuth(data.picture);
          updateProfileName(data.name);
          updateProfileTeam(data.email);
        }
      })
      .catch(err => console.error("❌ [Debug Parent Error]: Token exchange execution crashed:", err));
    }
  }
}

function updateUIAfterAuth(avatarUrl) {
  const imgElement = document.getElementById('profileAvatar');
  if (imgElement && avatarUrl) {
    imgElement.src = avatarUrl;
  }
  
  const authOverlay = document.getElementById('googleAuthOverlay');
  if (authOverlay) authOverlay.style.display = 'none';
  
  document.getElementById('uiLogoutTrigger').style.display = 'inline-flex';
}

function updateProfileName(name) {
    const profileName = document.getElementById("profileName");

    if (profileName && name) {
        profileName.textContent = name;
    }
}

function updateProfileTeam(teamText) {
    const profileTeam = document.getElementById("profileTeam");

    if (profileTeam && teamText) {
        profileTeam.textContent = teamText;
    }
}

function handleUserSignOut(event) {
  if (event) event.preventDefault();

  localStorage.removeItem('user_authenticated');
  localStorage.removeItem('user_avatar_url');
  localStorage.removeItem("access_token");
  
  // Restore default UI
    resetUserProfile();

  document.getElementById('profileAvatar').src = FALLBACK_AVATAR;
  document.getElementById('uiLogoutTrigger').style.display = 'block';
  
  const authOverlay = document.getElementById('googleAuthOverlay');
  if (authOverlay) authOverlay.style.display = 'block';
   // Verify logout
    if (localStorage.getItem("user_authenticated") !== "true") {
        console.log("✅ User successfully logged out.");
    } else {
        console.error("❌ Logout failed.");
    }
}

function resetUserProfile() {
	const name = document.getElementById("profileName");
    const team = document.getElementById("profileTeam");

    if (name) {
        name.textContent = DEFAULT_PROFILE.name;
    }

    if (team) {
        team.textContent = DEFAULT_PROFILE.team;
    }
}


function showToast(messageText) {
  const toastElement = document.getElementById('toast');
  if (!toastElement) {
    console.error("❌ [Toast Error]: Could not find '<div class=\"toast\" id=\"toast\"></div>' in your HTML.");
    return;
  }

  // 🖼️ 1. Set your exact working image path here (e.g., your real logo file destination)
  const logoPath = "./assets/images/pictureAliveAILogo_resize-new.png"; 

  // 🛠️ 2. Inject clean, isolated structures to completely bypass text styling crashes
  toastElement.innerHTML = `
    <!-- 🎯 The Glowing Logo Wrapper Container -->
    <div class="toast-logo-wrap" id="jsToastLogoBox">
      <img src="${logoPath}" alt="" id="jsToastImageNode">
    </div>
    
    <!-- 🎯 Main Text Content Area -->
    <div class="toast-content-block" style="display: flex !important; flex-direction: column !important; gap: 4px !important; flex-grow: 1 !important; text-align: left !important; background: transparent !important;">
      <div class="toast-title-text" style="font-size: 13px !important; font-weight: 800 !important; letter-spacing: 1.5px !important; text-transform: uppercase !important; color: #ffffff !important; text-shadow: 0 0 10px #ffffff, 0 0 20px #ff007f !important; background: transparent !important; -webkit-background-clip: initial !important; background-clip: initial !important; -webkit-text-fill-color: initial !important;">SYSTEM NOTIFICATION</div>
      <div class="toast-message-text" style="font-size: 12px !important; font-weight: 500 !important; line-height: 1.5 !important; color: #e0e0e0 !important; background: transparent !important; -webkit-background-clip: initial !important; background-clip: initial !important; -webkit-text-fill-color: initial !important;">${messageText}</div>
    </div>
    
    <!-- 🎯 Native Interactive Manual Close "X" Button -->
    <button class="toast-close-btn" id="closeToastCardTrigger" aria-label="Close notification" style="background: transparent !important; border: none !important; color: #888899 !important; cursor: pointer !important; display: flex !important; align-items: center !important; justify-content: center !important; padding: 6px !important; border-radius: 50% !important; flex-shrink: 0 !important; transition: all 0.2s ease !important;">
      <span class="material-symbols-outlined" style="font-size: 18px !important; pointer-events: none !important; background: transparent !important; -webkit-background-clip: initial !important; background-clip: initial !important; -webkit-text-fill-color: initial !important;">close</span>
    </button>
  `;

  // ==========================================================================
  // 🛠️ 3. CORE LAYOUT AND LIGHT GLOW STYLING INJECTION
  // ==========================================================================
  toastElement.style.display = "flex";
  toastElement.style.alignItems = "center";
  toastElement.style.gap = "18px";
  toastElement.style.position = "fixed";
  toastElement.style.top = "32px";
  toastElement.style.right = "32px";
  toastElement.style.left = "auto";
  
  // 🎯 Reset initial entry tracking states cleanly for animation re-triggers
  toastElement.style.transform = "translateX(0)";
  toastElement.style.opacity = "1";
  
  toastElement.style.width = "440px";
  toastElement.style.padding = "18px 22px";
  toastElement.style.borderRadius = "12px";
  toastElement.style.zIndex = "1000000";
  toastElement.style.boxSizing = "border-box";
  
  // 🟥 Outer perimeter bright laser neon red frame border line
  toastElement.style.border = "2px solid #ff1744";

  // Cyber backdrop mix (Hot pink and neon blue lights merging in dark panel canvas)
  toastElement.style.background = "linear-gradient(135deg, #09090b 0%, #121216 40%, rgba(255, 0, 127, 0.15) 75%, rgba(0, 229, 255, 0.1) 100%)";
  toastElement.style.boxShadow = "0 15px 40px rgba(0, 0, 0, 0.7), 0 0 25px rgba(255, 23, 68, 0.4), 0 0 50px rgba(255, 0, 127, 0.2), inset 0 0 15px rgba(0, 229, 255, 0.15);";

  // Reset explicit transition property parameters for the entrance framework
  toastElement.style.transition = "none";

  // Style the Cyan/Blue Logo Profile Wrapper Frame Box
  const logoBox = document.getElementById('jsToastLogoBox');
  if (logoBox) {
    logoBox.style.width = "48px";
    logoBox.style.height = "48px";
    logoBox.style.borderRadius = "8px";
    logoBox.style.display = "flex";
    logoBox.style.alignItems = "center";
    logoBox.style.justifyContent = "center";
    logoBox.style.flexShrink = "0";
    logoBox.style.overflow = "hidden";
    logoBox.style.background = "#000000";
    logoBox.style.border = "1px solid #00e5ff";
    logoBox.style.boxShadow = "0 0 12px rgba(0, 229, 255, 0.6)";
  }

  const logoImg = document.getElementById('jsToastImageNode');
  if (logoImg) {
    logoImg.style.width = "48px";
    logoImg.style.height = "48px";
    logoImg.style.maxWidth = "48px";
    logoImg.style.maxHeight = "48px";
    logoImg.style.objectFit = "cover";
    logoImg.style.display = "block";
    logoImg.style.opacity = "1";
    logoImg.style.visibility = "visible";
    logoImg.style.webkitBackgroundClip = "initial";
    logoImg.style.backgroundClip = "initial";
    logoImg.style.webkitTextFillColor = "initial";
  }

  // ==========================================================================
  // 🎯 4. THE DISMISS FUNCTION MAPPING WITH SLIDING FADE-OUT
  // ==========================================================================
  
  // Centralized reusable animation dismissal pipeline function
  const triggerAnimatedDismissal = () => {
    // 🎛️ Inject high-performance hardware accelerated exit transform values
    toastElement.style.transition = "transform 0.35s cubic-bezier(0.25, 1, 0.5, 1), opacity 0.3s linear";
    
    // Smoothly slides card 50px to the right while dissolving its light opacity to 0
    toastElement.style.transform = "translateX(50px)";
    toastElement.style.opacity = "0";

    // Wait exactly for the 350ms transition track duration to finish before cutting display paths
    setTimeout(() => {
      // Only hide layout if the element hasn't been re-triggered by another event loop
      if (toastElement.style.opacity === "0") {
        toastElement.style.display = "none";
      }
    }, 350);
  };

  const closeBtn = document.getElementById('closeToastCardTrigger');
  if (closeBtn) {
    closeBtn.onmouseenter = () => { closeBtn.style.color = "#ff1744"; closeBtn.style.background = "rgba(255, 23, 68, 0.15)"; };
    closeBtn.onmouseleave = () => { closeBtn.style.color = "#888899"; closeBtn.style.background = "transparent"; };

    closeBtn.onclick = function(e) {
      e.preventDefault();
      e.stopPropagation();
     // console.log("❌ [Toast System]: Close icon clicked. Running slide fade-out timeline...");
      triggerAnimatedDismissal();
    };
  }

  // ⏱️ 5. Auto-Dismiss Backup Loop (Triggers the identical smooth exit after 5 seconds)
  // Store the timer reference on the global container element window object to track overrides safely
  if (window.activeToastTimer) clearTimeout(window.activeToastTimer);
  
  window.activeToastTimer = setTimeout(() => {
    if (toastElement.style.display === "flex" && toastElement.style.opacity === "1") {
      //console.log("⏱️ [Toast System]: Timer expired. Running automatic slide fade-out...");
      triggerAnimatedDismissal();
    }
  }, 5000);
}

// 🧱 Clean animation disposal helper utility
function dismissToastCardInstantly(element) {
  if (toastRemovalTimer) clearTimeout(toastRemovalTimer);
  
  element.style.transition = "all 0.3s cubic-bezier(0.25, 1, 0.5, 1)";
  element.style.opacity = "0";
  element.style.transform = "translateY(-12px)";
  
  setTimeout(() => {
    element.classList.remove('show');
    element.style.transition = ""; 
    element.style.opacity = "";
    element.style.transform = "";
  }, 300);
}


