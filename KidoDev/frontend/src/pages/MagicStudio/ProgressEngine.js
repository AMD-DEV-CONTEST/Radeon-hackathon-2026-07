import { supabase } from '../../utils/supabaseClient';

export const LEVELS = [
    { name: 'Bronze', minXp: 0 },
    { name: 'Silver', minXp: 200 },
    { name: 'Gold', minXp: 500 },
    { name: 'Platinum', minXp: 1000 },
    { name: 'Diamond', minXp: 2000 },
];

export const BADGE_DEFINITIONS = [
    {
        id: 'first_run',
        label: 'Rocket First Launch',
        description: 'Complete your very first lesson',
        condition: ({ uniqueLessons, isFirstTimeForThisLesson }) =>
            uniqueLessons === 1 && isFirstTimeForThisLesson,
    },
    {
        id: 'perfectionist',
        label: '100 Perfectionist',
        description: 'Score 100 on any project',
        condition: ({ score }) => score === 100,
    },
    {
        id: 'speed_coder',
        label: 'Bolt Speed Coder',
        description: 'Complete a project in under 60 seconds',
        condition: ({ timeSeconds }) => timeSeconds > 0 && timeSeconds <= 60,
    },
    {
        id: 'minimalist',
        label: 'Broom Minimalist',
        description: 'Score 80+ using 5 or fewer blocks',
        condition: ({ score, blockCount }) =>
            score >= 80 && blockCount > 0 && blockCount <= 5,
    },
    {
        id: 'high_scorer',
        label: 'Star High Scorer',
        description: 'Score 90 or above',
        condition: ({ score }) => score >= 90,
    },
    {
        id: 'xp_100',
        label: 'Bronze Century Club',
        description: 'Earn 100 total XP',
        condition: ({ totalXp, prevTotalXp }) => totalXp >= 100 && prevTotalXp < 100,
    },
    {
        id: 'xp_500',
        label: 'Gold XP Champion',
        description: 'Earn 500 total XP',
        condition: ({ totalXp, prevTotalXp }) => totalXp >= 500 && prevTotalXp < 500,
    },
    {
        id: 'xp_1000',
        label: 'Diamond Coder',
        description: 'Earn 1000 total XP',
        condition: ({ totalXp, prevTotalXp }) => totalXp >= 1000 && prevTotalXp < 1000,
    },
    {
        id: 'lesson_5',
        label: 'Books Bookworm',
        description: 'Complete 5 different lessons',
        condition: ({ uniqueLessons, isFirstTimeForThisLesson }) =>
            uniqueLessons === 5 && isFirstTimeForThisLesson,
    },
    {
        id: 'lesson_10',
        label: 'Grad Graduate',
        description: 'Complete 10 different lessons',
        condition: ({ uniqueLessons, isFirstTimeForThisLesson }) =>
            uniqueLessons === 10 && isFirstTimeForThisLesson,
    },
];

export function calculateXp(score, timeSeconds, blockCount) {
    let xp = score;
    if (timeSeconds > 0 && timeSeconds <= 60) xp += 30;
    else if (timeSeconds <= 120) xp += 15;
    else if (timeSeconds <= 300) xp += 5;
    if (blockCount >= 1 && blockCount <= 5) xp += 20;
    else if (blockCount <= 10) xp += 10;
    return xp;
}

export function getLevelFromXp(totalXp) {
    let current = LEVELS[0];
    for (const lvl of LEVELS) {
        if (totalXp >= lvl.minXp) current = lvl;
    }
    return current.name;
}

export function getXpProgress(totalXp) {
    for (let i = 0; i < LEVELS.length - 1; i++) {
        if (totalXp < LEVELS[i + 1].minXp) {
            return {
                current: totalXp - LEVELS[i].minXp,
                next: LEVELS[i + 1].minXp - LEVELS[i].minXp,
                nextLevelName: LEVELS[i + 1].name,
            };
        }
    }
    return { current: totalXp, next: totalXp, nextLevelName: null };
}

export function getProjectBadge(score) {
    if (score >= 90) return 'Gold Medal';
    if (score >= 70) return 'Silver Medal';
    if (score >= 50) return 'Bronze Medal';
    return 'Target Participant';
}

export function resolveNewBadges(existingBadgeIds, stats) {
    const existing = new Set(existingBadgeIds || []);
    return BADGE_DEFINITIONS
        .filter(b => !existing.has(b.id) && b.condition(stats))
        .map(b => b.id);
}

export async function awardProgress({ userId, lessonId, score, startTime, blockCount }) {
    try {
        const timeSeconds = Math.floor((Date.now() - startTime) / 1000);
        const projectBadge = getProjectBadge(score);

        // ── 1. Fetch profile
        const { data: profile, error: profileError } = await supabase
            .from('child_profiles')
            .select('total_xp, level, badges')
            .eq('id', userId)
            .maybeSingle();
        if (profileError || !profile) return null;

        const prevXp = profile.total_xp || 0;
        const prevLevel = profile.level || 'Bronze';
        const prevBadges = profile.badges || [];

        // ── 2. Fetch all project rows for this lesson
        const { data: existingProjects } = await supabase
            .from('projects')
            .select('xp_earned')
            .eq('user_id', userId)
            .eq('lesson_id', lessonId)
            .order('created_at', { ascending: false })
            .limit(1);
        const prevLessonXp = existingProjects?.[0]?.xp_earned || 0;

        // ── 3. Compute XP for this attempt
        const thisAttemptXp = calculateXp(score, timeSeconds, blockCount);
        const xpEarned = Math.max(prevLessonXp, thisAttemptXp);
        const xpDelta = xpEarned - prevLessonXp; // how much to add to total XP
        const newTotalXp = prevXp + xpDelta;
        const newLevel = getLevelFromXp(newTotalXp);
        const levelUp = newLevel !== prevLevel;

        // ── 4. Fetch all projects to count unique lessons
        const { data: allProjects } = await supabase
            .from('projects')
            .select('lesson_id')
            .eq('user_id', userId);
        const allLessonIds = (allProjects || []).map(r => r.lesson_id);
        const uniqueLessonSet = new Set(allLessonIds);
        const timesThisLesson = allLessonIds.filter(id => id === lessonId).length;
        const isFirstTimeForThisLesson = timesThisLesson <= 1;
        const uniqueLessons = uniqueLessonSet.size;

        // ── 5. Badges
        const stats = {
            score, timeSeconds, blockCount,
            totalXp: newTotalXp,
            prevTotalXp: prevXp,
            uniqueLessons,
            isFirstTimeForThisLesson,
        };
        const newBadgeIds = resolveNewBadges(prevBadges, stats);
        const updatedBadges = [...prevBadges, ...newBadgeIds];
        const newBadgeLabels = newBadgeIds.map(id => BADGE_DEFINITIONS.find(b => b.id === id)?.label || id);

        // ── 6. Update projects row if XP improved or badge changed
        if (xpEarned > prevLessonXp || projectBadge !== existingProjects?.[0]?.badge) {
            await supabase
                .from('projects')
                .update({ xp_earned: xpEarned, time_seconds: timeSeconds, block_count: blockCount, badge: projectBadge })
                .eq('user_id', userId)
                .eq('lesson_id', lessonId)
                .order('created_at', { ascending: false })
                .limit(1);
        }

        // ── 7. Update child_profile if anything changed
        const somethingChanged = xpDelta > 0 || newBadgeIds.length > 0 || levelUp;
        if (somethingChanged) {
            await supabase
                .from('child_profiles')
                .update({ total_xp: newTotalXp, level: newLevel, badges: updatedBadges })
                .eq('id', userId);
        }

        // ── 8. Synchronize with lesson_completions (Used by Levels Map)
        const { data: existingComp } = await supabase
            .from('lesson_completions')
            .select('id, score')
            .eq('child_id', userId)
            .eq('lesson_id', lessonId)
            .maybeSingle();

        if (!existingComp) {
            await supabase.from('lesson_completions').insert([{
                child_id: userId,
                lesson_id: lessonId,
                score: score,
                badge: projectBadge
            }]);
        } else if (score > (existingComp.score || 0)) {
            await supabase.from('lesson_completions').update({
                score: score,
                badge: projectBadge
            }).eq('id', existingComp.id);
        }

        return {
            xpEarned, totalXp: newTotalXp, badge: projectBadge,
            newLevel, levelUp,
            newBadges: newBadgeIds, newBadgeLabels,
            isFirstTimeForThisLesson,
        };
    } catch (err) {
        return null;
    }
}

export async function fetchStudentProgress(userId) {
    try {
        const [profileRes, projectsRes] = await Promise.all([
            supabase.from('child_profiles').select('total_xp, level, badges').eq('id', userId).maybeSingle(),
            supabase.from('projects').select('score, lesson_id').eq('user_id', userId),
        ]);
        if (!profileRes.data) return null;

        const profile = profileRes.data;
        const projects = projectsRes.data || [];
        const totalXp = profile.total_xp || 0;
        const badgeIds = profile.badges || [];
        const badgeLabels = badgeIds.map(id => BADGE_DEFINITIONS.find(b => b.id === id)?.label || id);
        const topScore = projects.length ? Math.max(...projects.map(p => p.score || 0)) : 0;
        const uniqueLessons = new Set(projects.map(p => p.lesson_id)).size;

        return { totalXp, level: profile.level || 'Bronze', badges: badgeIds, badgeLabels, xpProgress: getXpProgress(totalXp), uniqueLessons, topScore };
    } catch (err) {
        console.error('[fetchStudentProgress] error:', err);
        return null;
    }
}