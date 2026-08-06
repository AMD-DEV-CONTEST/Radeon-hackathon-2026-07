import { useNavigate } from 'react-router-dom';
import { useTheme } from '../utils/ThemeContext';
import heroVideo from '../assets/herovideo.mp4';

const Hero = () => {
    const navigate = useNavigate();
    const { theme } = useTheme();

    const getHeroContent = () => {
        switch (theme) {
            case 'princess':
                return {
                    title: <>Create Your <span className="word-own">Royal</span> <br /><span className="word-magical">Crystal</span> <span className="word-world">Kingdom</span></>
                };
            default: // forest
                return {
                    title: (
                        <>
                            Learn Coding the <br />
                            <span 
                                className="word-easy" 
                                style={{ 
                                    color: '#00FF66', 
                                    display: 'inline-block'
                                }}
                            >
                                Easy
                            </span>
                            {' '}
                            &
                            {' '}
                            <span 
                                className="word-best" 
                                style={{ 
                                    color: '#FF007F', 
                                    display: 'inline-block'
                                }}
                            >
                                Best
                            </span>
                            {' '}
                            Way!
                        </>
                    )
                };
        }
    };

    const content = getHeroContent();

    return (
        <section className={`hero-section-premium ${theme}-hero`}>
            {/* Video Background */}
            <video 
                autoPlay 
                loop 
                muted 
                playsInline 
                className="hero-video-bg"
            >
                <source src={heroVideo} type="video/mp4" />
            </video>
            
            {/* Dark Overlay for Text Readability */}
            <div className="hero-dark-overlay"></div>

            <div className="container position-relative z-10 text-center">
                <div className="hero-content-wrapper">

                    <h1 className="sota-h1-colorful">
                        {content.title}
                    </h1>
                    
                    <div className="sota-cta-colorful mb-5 mt-4">
                        <button 
                            className="btn btn-hero-vibrant"
                            onClick={() => navigate('/levels')}
                        >
                            Start Your Mission
                        </button>
                    </div>
                </div>
            </div>
        </section>
    );
};

export default Hero;
