import React from 'react';
import { useTheme } from '../../utils/ThemeContext';
import './SpriteLoader.css';

/**
 * Premium Sprite Loader
 * @param {boolean} show - Controls visibility
 * @param {boolean} fullScreen - If true, covers entire viewport. If false, stays relative to parent.
 */
const SpriteLoader = ({ show = true, fullScreen = true }) => {
    const { themeAssets } = useTheme();
    const logo = themeAssets?.sprite_logo || '/assets/no_bg_output/sprite-logo_nobg.webp';

    if (!show) return null;

    return (
        <div className={fullScreen ? "sprite-loader-portal-overlay" : "sprite-loader-page-relative"}>
            <div className="sprite-portal-container">
                {/* Rotating Magic Rings */}
                <div className="magic-ring ring-1"></div>
                <div className="magic-ring ring-2"></div>
                <div className="magic-ring ring-3"></div>
                
                {/* Glowing Core with Real Animated Sprite */}
                <div className="portal-core">
                    <div className="portal-glow"></div>
                    <div className="cat-sprite-wrap">
                        <img 
                            src={logo} 
                            alt="Sprite" 
                            className="premium-cat-icon" 
                        />
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SpriteLoader;
