import React from 'react';
import Hero from '../components/Hero';
import Features from '../components/Features';
import HowItWorks from '../components/HowItWorks';
import Syllabus from '../components/Syllabus';
import Team from '../components/Team';

const Home = () => {
    return (
        <React.Fragment>
            <Hero />
            <Features />
            <HowItWorks />
            <Syllabus />
            <Team />
        </React.Fragment>
    );
};

export default Home;
