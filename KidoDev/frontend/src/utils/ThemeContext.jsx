import React, { createContext, useContext, useState, useEffect } from 'react';
import { supabase } from './supabaseClient';

// Optimized No-BG WebP Assets (from no_bg_output folder)
import logoMain from '../assets/no_bg_output/logo_nobg.webp';
import spriteLogo from '../assets/no_bg_output/sprite-logo_nobg.webp';
import forestHeroChar from '../assets/no_bg_output/hero_nobg.webp';


// Forest assets
import forestStone from '../assets/no_bg_output/levels_stone_nobg.webp';
import forestHero from '../assets/no_bg_output/levels_hero_nobg.webp';
import forestLineConnect from '../assets/no_bg_output/level_line_connect_nobg.webp';
import forestLine from '../assets/no_bg_output/levels_line_nobg.webp';
import forestNode from '../assets/no_bg_output/level_node_nobg.webp';
import forestImage from '../assets/no_bg_output/levels_image_nobg.webp';




// Princess assets (handling typos in filenames)
import princessStone from '../assets/no_bg_output/princess_levels_stone_nobg.webp';
import princessHero from '../assets/no_bg_output/princess_levels_hero_nobg.webp';
import princessLineConnect from '../assets/no_bg_output/princiess_level-line_connect_nobg.webp';
import princessLine from '../assets/no_bg_output/priness_levels_line_nobg.webp';
import princessNode from '../assets/no_bg_output/princess_level_node_nobg.webp';
import princessImage from '../assets/no_bg_output/princess_level_image_nobg.webp';

// Dynamic URL for heavy 7.45MB background asset to avoid bundling in critical JS path
const princessMainBg = new URL('../assets/princessmain.webp', import.meta.url).href;

const ThemeContext = createContext();

export const ThemeProvider = ({ children }) => {
    const [theme, setTheme] = useState(localStorage.getItem('kido_theme') || 'forest');

    const themes = {
        forest: {
            name: 'Forest',
            logo: logoMain,
            sprite_logo: spriteLogo,
            hero: forestHeroChar, // Character
            levels_stone: forestStone,
            levels_hero: forestHero, // Levels Character
            levels_conecting_line: forestLineConnect,
            levels_line: forestLine,
            levels_node: forestNode,
            levels_image: forestImage, // Landscape
            primary: '#4CAF50',
            secondary: '#FFC107',
            accent: '#FF5722',
            navbar_bg: 'rgba(13, 27, 13, 0.85)',
            navbar_text: '#FFFFFF',
            node_font_color: '#FFFFFF',
            primary_rgb: '76, 175, 80', // RGB for #4CAF50
            badge_unlocked_bg: '#4CAF50',
            badge_locked_bg: '#F44336',
            badge_unlocked_text: '#FFFFFF',
            badge_locked_text: '#FFFFFF',
            stone_title_color: 'linear-gradient(180deg, #FF5722 0%, #FF9800 100%)',
            stone_progress_color: '#4CAF50',
            stone_xp_text_color: '#E65100',
            stone_label_color: '#5D4037',
            stone_missions_color: '#212121',
            stone_mastery_color: '#8D6E63'
        },
        princess: {
            name: 'Princess',
            logo: logoMain,
            sprite_logo: spriteLogo,
            hero: princessHero, // Character
            levels_stone: princessStone,
            levels_hero: princessMainBg, // Map Background
            levels_conecting_line: princessLineConnect,
            levels_line: princessLine,
            levels_node: princessNode,
            levels_image: princessImage, // Selection Page (Landscape)
            primary: '#9C27B0',
            secondary: '#FFD700',
            accent: '#BA68C8',
            navbar_bg: 'rgba(156, 39, 176, 0.85)',
            navbar_text: '#FFFFFF',
            node_font_color: '#FFFFFF',
            primary_rgb: '156, 39, 176', // RGB for #9C27B0
            badge_unlocked_bg: '#9C27B0',
            badge_locked_bg: '#E1BEE7',
            badge_unlocked_text: '#FFFFFF',
            badge_locked_text: '#4A148C',
            stone_title_color: 'linear-gradient(180deg, #BA68C8 0%, #9C27B0 100%)',
            stone_progress_color: '#9C27B0',
            stone_xp_text_color: '#4A148C',
            stone_label_color: '#4A148C',
            stone_missions_color: '#6A1B9A',
            stone_mastery_color: '#6A1B9A'
        }
    };

    const changeTheme = async (newTheme) => {
        if (!themes[newTheme]) return;
        
        setTheme(newTheme);
        localStorage.setItem('kido_theme', newTheme);

        // Sync with Supabase asynchronously
        const childId = localStorage.getItem('kido_child_id');
        const role = localStorage.getItem('kido_auth_role');

        if (role === 'kid' && childId) {
            await supabase.from('children').update({ theme: newTheme }).eq('id', childId);
        } else if (role === 'parent') {
            const { data: { user } } = await supabase.auth.getUser();
            if (user) {
                await supabase.from('parent_profiles').update({ theme: newTheme }).eq('id', user.id);
            }
        }
    };

    const toggleTheme = () => {
        const themeKeys = Object.keys(themes);
        const currentIndex = themeKeys.indexOf(theme);
        const nextIndex = (currentIndex + 1) % themeKeys.length;
        changeTheme(themeKeys[nextIndex]);
    };

    useEffect(() => {
        const fetchRemoteTheme = async (userId, role, childId) => {
            let remoteTheme = null;
            try {
                if (role === 'kid' && childId) {
                    const { data } = await supabase.from('children').select('theme').eq('id', childId).single();
                    remoteTheme = data?.theme;
                } else if (role === 'parent' && userId) {
                    const { data } = await supabase.from('parent_profiles').select('theme').eq('id', userId).single();
                    remoteTheme = data?.theme;
                }

                if (remoteTheme) {
                    setTheme(prev => {
                        if (prev !== remoteTheme) {
                            localStorage.setItem('kido_theme', remoteTheme);
                            return remoteTheme;
                        }
                        return prev;
                    });
                }
            } catch (err) {
                console.error("Theme sync error:", err);
            }
        };

        // Only fetch remote theme if there is an active session role saved
        const childId = localStorage.getItem('kido_child_id');
        const role = localStorage.getItem('kido_auth_role');
        if (role && (role === 'kid' || role === 'parent')) {
            supabase.auth.getUser().then(({ data: { user } }) => {
                if (user || childId) {
                    fetchRemoteTheme(user?.id, role, childId);
                }
            });
        }

        // Listen for auth changes
        const { data: { subscription } } = supabase.auth.onAuthStateChange(async (event, session) => {
            const currentRole = localStorage.getItem('kido_auth_role');
            const currentChildId = localStorage.getItem('kido_child_id');
            
            if (event === 'SIGNED_IN' || session?.user || currentChildId) {
                await fetchRemoteTheme(session?.user?.id, currentRole, currentChildId);
            }
        });

        // Listen for manual updates from useAuthForm
        const handleManualUpdate = () => {
            const savedTheme = localStorage.getItem('kido_theme');
            if (savedTheme) {
                setTheme(prev => prev !== savedTheme ? savedTheme : prev);
            }
        };
        window.addEventListener('kido_theme_changed', handleManualUpdate);

        return () => {
            subscription.unsubscribe();
            window.removeEventListener('kido_theme_changed', handleManualUpdate);
        };
    }, []); // RUN ONCE ON MOUNT

    useEffect(() => {
        const root = document.documentElement;
        const currentAssets = themes[theme] || themes.forest;
        
        // Apply CSS variables for SCSS backgrounds
        root.style.setProperty('--theme-primary', currentAssets.primary);
        root.style.setProperty('--theme-primary-rgb', currentAssets.primary_rgb);
        root.style.setProperty('--theme-secondary', currentAssets.secondary);
        root.style.setProperty('--theme-accent', currentAssets.accent);
        root.style.setProperty('--navbar-bg', currentAssets.navbar_bg);
        root.style.setProperty('--navbar-text', currentAssets.navbar_text);
        root.style.setProperty('--node-font-color', currentAssets.node_font_color);
        root.style.setProperty('--badge-unlocked-bg', currentAssets.badge_unlocked_bg);
        root.style.setProperty('--badge-locked-bg', currentAssets.badge_locked_bg);
        root.style.setProperty('--badge-unlocked-text', currentAssets.badge_unlocked_text);
        root.style.setProperty('--badge-locked-text', currentAssets.badge_locked_text);
        root.style.setProperty('--stone-title-color', currentAssets.stone_title_color);
        root.style.setProperty('--stone-progress-color', currentAssets.stone_progress_color);
        root.style.setProperty('--stone-xp-text-color', currentAssets.stone_xp_text_color);
        root.style.setProperty('--stone-label-color', currentAssets.stone_label_color);
        root.style.setProperty('--stone-missions-color', currentAssets.stone_missions_color);
        root.style.setProperty('--stone-mastery-color', currentAssets.stone_mastery_color);

        // Special override for Spider and Princess selection background
        let selectionBg = currentAssets.levels_hero;
        if (theme === 'spider' || theme === 'princess') {
            selectionBg = currentAssets.levels_image;
        }
        root.style.setProperty('--levels-hero-bg', `url("${selectionBg}")`);
        
        root.style.setProperty('--level-line-connect-bg', `url("${currentAssets.levels_conecting_line}")`);
        
        root.setAttribute('data-theme', theme);
    }, [theme]);

    return (
        <ThemeContext.Provider value={{ theme, toggleTheme, changeTheme, themes, themeAssets: themes[theme] || themes.forest }}>
            {children}
        </ThemeContext.Provider>
    );
};

export const useTheme = () => {
    const context = useContext(ThemeContext);
    if (!context) {
        throw new Error('useTheme must be used within a ThemeProvider');
    }
    return context;
};
