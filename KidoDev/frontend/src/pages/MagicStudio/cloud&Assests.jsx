// cloudAndAssets.js

// ============================================================
// PROFESSOR KIDO — GRADING + CLOUD SAVE
// ============================================================

export async function gradeAndSaveProject({
    lessonId,
    curXml,
    sprites,
    backdrops,
    currentBackdrop,
    variables,
    lists,
    supabase,
    getGrade,
    addLog,
    setGradingResult
}) {
    try {
        // ----------------------------
        // 1️⃣ Grade project
        // ----------------------------
        const { score, feedback } = getGrade(lessonId, curXml, sprites);
        setGradingResult({ score, feedback });

        // ----------------------------
        // 2️⃣ Get logged-in user
        // ----------------------------
        const {
            data: { user }
        } = await supabase.auth.getUser();

        if (!user) {
            addLog("⚠️ Offline mode: score calculated but not saved.");
            return { score, feedback };
        }

        addLog("☁️ Saving project to cloud...");

        // ----------------------------
        // 3️⃣ Prepare project data
        // ----------------------------
        const projectData = {
            targets: sprites,
            backdrops,
            currentBackdrop,
            variables,
            lists,
            lastUpdated: new Date().toISOString()
        };

        const fileName = `project_${Date.now()}.sb3`;
        const filePath = `${user.id}/${lessonId}/${fileName}`;

        const blob = new Blob([JSON.stringify(projectData)], {
            type: "application/json"
        });

        // ----------------------------
        // 4️⃣ Upload to storage bucket
        // ----------------------------
        const { error: uploadError } = await supabase.storage
            .from("projects")
            .upload(filePath, blob, { upsert: true });

        if (uploadError) throw uploadError;

        // ----------------------------
        // 5️⃣ Insert DB row
        // ----------------------------
        const { error: insertError } = await supabase
            .from("projects")
            .insert({
                user_id: user.id,
                lesson_id: lessonId,
                file_path: filePath,
                score,
                feedback
            });

        if (insertError) throw insertError;

        addLog(`🎓 Professor Kido marked it: ${score}/100`);
        addLog("✨ Adventure saved to your cloud locker!");

        return { score, feedback };
    } catch (err) {
        console.error("Cloud save failed:", err);
        addLog("❌ Cloud save failed");
        return null;
    }
}

// ============================================================
// ASSET MANAGEMENT
// ============================================================

export function addSprite({ spriteData, spritesRef, setSprites, addLog }) {
    const newSprite = {
        id: `sprite_${Date.now()}`,
        name: spriteData.name || "Sprite",
        x: 0,
        y: 0,
        direction: 90,
        size: 100,
        visible: true,
        costumes: spriteData.costumes || [],
        sounds: spriteData.sounds || [],
        variables: {},
        lists: {}
    };

    spritesRef.current.push(newSprite);
    setSprites([...spritesRef.current]);
    addLog(`🧩 Added sprite: ${newSprite.name}`);
}

export function switchBackdrop({ backdropName, setCurrentBackdrop, addLog }) {
    if (!backdropName) return;
    setCurrentBackdrop(backdropName);
    addLog(`🎬 Backdrop switched to: ${backdropName}`);
}

export function addSoundToSprite({ spriteId, soundData, spritesRef, setSprites, addLog }) {
    const sprite = spritesRef.current.find(s => s.id === spriteId);
    if (!sprite) return;

    sprite.sounds.push(soundData);
    setSprites([...spritesRef.current]);
    addLog(`🔊 Sound added to ${sprite.name}`);
}

// ============================================================
// VARIABLE & LIST HELPERS
// ============================================================

export function createVariable({ name, variablesRef, setVariables, addLog }) {
    if (!name || variablesRef.current[name] !== undefined) return;

    variablesRef.current[name] = 0;
    setVariables({ ...variablesRef.current });
    addLog(`📦 Variable created: ${name}`);
}

export function createList({ name, listsRef, setLists, addLog }) {
    if (!name || listsRef.current[name] !== undefined) return;

    listsRef.current[name] = [];
    setLists({ ...listsRef.current });
    addLog(`📚 List created: ${name}`);
}