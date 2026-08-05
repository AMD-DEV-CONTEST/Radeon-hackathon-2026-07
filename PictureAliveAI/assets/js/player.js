document.addEventListener('DOMContentLoaded', () => {
  const playButton = document.getElementById('playPreview');
  const audioPlay = document.getElementById('audioPlayToggle');
  const scrubberFill = document.querySelector('.scrubber-fill');
  const audioProgress = document.querySelector('.audio-progress');
  
  //sample output for ui 
  const audio = document.getElementById('realAudio');
  const playToggleBtn = document.getElementById('audioPlayToggle');
  const playIcon = document.getElementById('playIcon');
  const timeDisplay = document.getElementById('timeDisplay');
  const progressBar = document.getElementById('audioProgressBar');
  const timeline = document.getElementById('trackTimeline');
  const downloadBtn = document.getElementById('audioDownloadTrigger');

  let previewAnimating = false;
  let audioAnimating = false;
  let toastRemovalTimer = null;


  audioPlay?.addEventListener('click', () => {
    audioAnimating = !audioAnimating;
    audioProgress.style.width = audioAnimating ? '70%' : '33%';
    showToast(audioAnimating ? 'Audio playing' : 'Audio paused');
  });
  
  // Convert raw seconds into neat MM:SS layout strings
  function formatTime(seconds) {
    if (isNaN(seconds) || !isFinite(seconds)) return "00:00";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }
  
  // Update display values smoothly
  function updateTimeDisplay() {
    const current = formatTime(audio.currentTime);
    const total = formatTime(audio.duration);
    timeDisplay.textContent = `${current} / ${total}`;
  }
  
  // ⚡ Fix: Immediately check if audio metadata is already ready in memory
  if (audio.readyState >= 1) {
    updateTimeDisplay();
  } else {
    // Fallback: Listen if it finishes loading a split-second later [1]
    audio.addEventListener('loadedmetadata', updateTimeDisplay);
  }

  // Populate total duration metadata as soon as file properties initialize
  audio.addEventListener('loadedmetadata', () => {
    timeDisplay.textContent = `00:00 / ${formatTime(audio.duration)}`;
  });

  // Toggle media execution playback state transitions
  playToggleBtn.addEventListener('click', () => {
    if (audio.paused) {
      audio.play();
      playIcon.textContent = 'pause'; // Changes icon symbol keyword dynamically
    } else {
      audio.pause();
      playIcon.textContent = 'play_arrow';
    }
  });

  // Track progress and update the timer numbers on every single tick
  audio.addEventListener('timeupdate', () => {
    if (audio.duration) {
      const progressPercent = (audio.currentTime / audio.duration) * 100;
      progressBar.style.width = `${progressPercent}%`;
    }
    updateTimeDisplay(); // Keeps ticking up from 00:00 natively
  });

  // Reset tracking layout on file termination
  audio.addEventListener('ended', () => {
    playIcon.textContent = 'play_arrow';
    progressBar.style.width = '0%';
    audio.currentTime = 0;
    updateTimeDisplay();
  });

  // Manual scrub selector handler
  timeline.addEventListener('click', (e) => {
    const timelineWidth = timeline.clientWidth;
    const clickPositionX = e.offsetX;
    const clickFraction = clickPositionX / timelineWidth;
    if (audio.duration) {
      audio.currentTime = clickFraction * audio.duration;
    }
  });

  // Native File Storage Downloader Mechanism
  downloadBtn.addEventListener('click', () => {
    const downloadAnchor = document.createElement('a');
    downloadAnchor.href = ("/assets/images/PICTURE-ALIVE-AI-SAMPLE-HISTORICAL-RESPONSE.mp3"); // Extracts path target string ("./images/your-audio-file.mp3")
    downloadAnchor.download = 'picture-alive-ai-sample-preview.mp3'; // Hardcoded fallback output file name string
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click(); // Fires programmatic document click trigger
    document.body.removeChild(downloadAnchor); // Trash memory reference footprint nodes instantly
  });

  
});



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

