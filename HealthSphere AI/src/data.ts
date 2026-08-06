import { DiseaseInfo, EmergencyContact, HospitalInfo, HealthTip } from "./types";

export const DISEASE_LIBRARY: DiseaseInfo[] = [
  {
    id: "dengue",
    name: "Dengue Fever",
    category: "Vector-borne Viral Infection",
    overview: "Dengue is a viral infection transmitted to humans through the bite of infected female Aedes mosquitoes, primarily Aedes aegypti. It is common in tropical and subtropical climates worldwide.",
    symptoms: [
      "Severe high fever (often reaching 104°F / 40°C)",
      "Severe headache, especially pain behind the eyes",
      "Muscle, joint, and bone pains (frequently referred to as 'breakbone fever')",
      "Nausea, vomiting, and loss of appetite",
      "Skin rash appearing 2 to 5 days after the onset of fever",
      "Mild bleeding (such as nose bleeds, bleeding gums, or easy bruising)"
    ],
    prevention: [
      "Eliminate standing water in and around the home where mosquitoes lay eggs",
      "Apply insect repellent containing DEET, Picaridin, or IR3535",
      "Wear protective clothing, such as long-sleeved shirts and long pants",
      "Use mosquito nets while sleeping, especially during daytime when Aedes bite",
      "Install window and door screens to keep mosquitoes out of living areas"
    ],
    causes: [
      "Transmission of any of the four dengue virus serotypes (DENV-1 to DENV-4) via mosquito bites",
      "The mosquito becomes infected when it bites an infected human and then transmits the virus to another person"
    ],
    severity: "High"
  },
  {
    id: "flu",
    name: "Influenza (Flu)",
    category: "Respiratory Viral Infection",
    overview: "Influenza is a contagious respiratory illness caused by influenza viruses that infect the nose, throat, and sometimes the lungs. It can range from mild to severe illness.",
    symptoms: [
      "Fever or feeling feverish/chills",
      "Cough and sore throat",
      "Runny or stuffy nose",
      "Muscle or body aches",
      "Headaches and extreme fatigue",
      "Some people may experience vomiting and diarrhea (more common in children)"
    ],
    prevention: [
      "Receive an annual seasonal flu vaccine (the single best preventive measure)",
      "Wash hands frequently and thoroughly with soap and water or alcohol-based sanitizer",
      "Avoid close contact with people who are sick",
      "Cover coughs and sneezes with a tissue or your elbow",
      "Stay home from work or school when sick to prevent spreading the virus"
    ],
    causes: [
      "Influenza viruses (mostly Type A and Type B) spreading through respiratory droplets produced when people cough, sneeze, or talk"
    ],
    severity: "Medium"
  },
  {
    id: "covid",
    name: "COVID-19",
    category: "Respiratory Viral Pandemic",
    overview: "COVID-19 is an infectious disease caused by the SARS-CoV-2 virus. It primarily attacks the respiratory system and spreads easily from person to person.",
    symptoms: [
      "Fever, dry cough, and shortness of breath or difficulty breathing",
      "Fatigue, muscle or body aches",
      "New loss of taste or smell",
      "Sore throat, congestion, or runny nose",
      "Nausea, vomiting, or diarrhea",
      "Severe cases may involve persistent chest pain, confusion, or bluish lips/face"
    ],
    prevention: [
      "Stay up to date with COVID-19 vaccines and booster doses",
      "Wear high-quality masks in crowded or poorly ventilated indoor public spaces",
      "Improve ventilation indoors by opening windows or using air filters",
      "Practice regular hand hygiene and respiratory etiquette",
      "Perform self-tests if symptomatic and isolate if you test positive"
    ],
    causes: [
      "Infection with the SARS-CoV-2 coronavirus, transmitted through droplets and aerosols when an infected person breathes, coughs, sneezes, or talks"
    ],
    severity: "High"
  },
  {
    id: "diabetes",
    name: "Diabetes Mellitus",
    category: "Metabolic/Chronic Disease",
    overview: "Diabetes is a chronic, metabolic disease characterized by elevated levels of blood glucose (or blood sugar), which leads over time to serious damage to the heart, blood vessels, eyes, kidneys, and nerves.",
    symptoms: [
      "Increased thirst (polydipsia) and frequent urination (polyuria)",
      "Extreme hunger and unexplained weight loss",
      "Presence of ketones in the urine (a byproduct of muscle breakdown)",
      "Fatigue, irritability, and blurred vision",
      "Slow-healing sores or cuts",
      "Frequent infections, such as gums or skin infections"
    ],
    prevention: [
      "Maintain a healthy body weight through balanced calorie consumption",
      "Engage in at least 150 minutes of moderate-intensity physical activity per week",
      "Eat a healthy diet rich in fiber, whole grains, vegetables, and lean proteins",
      "Limit consumption of sugar-sweetened beverages and highly processed foods",
      "Avoid tobacco use, which increases the risk of cardiovascular disease in diabetics"
    ],
    causes: [
      "Type 1: Autoimmune reaction where the body's immune system destroys insulin-producing beta cells in the pancreas",
      "Type 2: Progressive insulin resistance where body cells do not respond effectively to insulin, often linked to genetics and excess body weight"
    ],
    severity: "Medium"
  },
  {
    id: "heart_disease",
    name: "Cardiovascular (Heart) Disease",
    category: "Cardiovascular/Chronic Condition",
    overview: "Cardiovascular disease (CVD) is a general term for conditions affecting the heart or blood vessels. It is most commonly associated with atherosclerosis (plaque buildup in the arteries).",
    symptoms: [
      "Chest pain, chest tightness, chest pressure, and chest discomfort (angina)",
      "Shortness of breath, especially during exertion or while lying flat",
      "Pain, numbness, weakness, or coldness in your legs or arms if blood vessels are narrowed",
      "Pain in the neck, jaw, throat, upper abdomen, or back",
      "Fluttering in your chest, rapid heartbeat (tachycardia), or slow heartbeat (bradycardia)"
    ],
    prevention: [
      "Adopt a heart-healthy diet low in saturated fats, trans fats, and sodium",
      "Exercise regularly to improve arterial elasticity and strengthen the heart muscle",
      "Manage stress through mindfulness, meditation, or therapy",
      "Monitor and control blood pressure, cholesterol levels, and blood sugar levels",
      "Avoid smoking and limit alcohol consumption"
    ],
    causes: [
      "Atherosclerosis (accumulation of fatty plaques in your arteries)",
      "Congenital heart defects, high blood pressure, diabetes, physical inactivity, obesity, and hereditary genetic traits"
    ],
    severity: "High"
  },
  {
    id: "asthma",
    name: "Asthma",
    category: "Chronic Respiratory Disease",
    overview: "Asthma is a chronic condition that affects the airways in the lungs, causing them to become inflamed, narrow, and swollen, making breathing difficult and triggering coughing, wheezing, and shortness of breath.",
    symptoms: [
      "Shortness of breath and difficulty exhaling completely",
      "Chest tightness or pain",
      "Wheezing when exhaling, which is a common sign of asthma in children",
      "Trouble sleeping caused by shortness of breath, coughing, or wheezing",
      "Coughing or wheezing attacks that are worsened by a respiratory virus"
    ],
    prevention: [
      "Identify and strictly avoid asthma triggers (e.g., pollen, dust mites, pet dander, mold, cold air, smoke)",
      "Monitor your breathing and recognize early signs of a worsening flare-up",
      "Take prescribed long-term control medications (such as inhaled corticosteroids) consistently",
      "Get vaccinated for influenza and pneumonia to prevent severe respiratory triggers"
    ],
    causes: [
      "An oversensitive airway immune system that reacts strongly to airborne substances, exercise, cold air, or physical stress. Strongly influenced by genetic factors and early childhood environmental exposure."
    ],
    severity: "Medium"
  }
];

export const HEALTH_TIPS: HealthTip[] = [
  {
    category: "Vaccination",
    title: "Stay Safeguarded with Seasonal Boosters",
    description: "Immunizations are your shield against highly contagious diseases. Annual influenza shots and updated COVID-19 boosters train your immune system, protecting you and high-risk community members."
  },
  {
    category: "Hygiene",
    title: "The Art of Hand Hygiene",
    description: "Washing your hands with soap and warm water for at least 20 seconds remains the single most effective way to stop the spread of viruses. Always clean hands before meals and after visiting public spaces."
  },
  {
    category: "Nutrition",
    title: "Fueling the Immune System",
    description: "Incorporate a vibrant rainbow of fruits and vegetables into your daily diet. Leafy greens, citrus fruits, berries, and nuts provide crucial vitamins (C, D) and zinc to support cellular defense."
  },
  {
    category: "Mental Health",
    title: "Decompressing the Nervous System",
    description: "Chronic stress elevates cortisol, suppressing immune function. Dedicate 10 minutes daily to diaphragmatic breathing, structured meditation, or off-screen outdoor walking to recalibrate."
  },
  {
    category: "Exercise",
    title: "Consistent Moderate Activity",
    description: "Engaging in 30 minutes of moderate activity like brisk walking, cycling, or yoga boosts blood circulation. This promotes rapid movement of white blood cells to detect and fight infections."
  },
  {
    category: "First Aid",
    title: "Basic Burn and Wound Response",
    description: "For minor burns, immediately run cool water over the area for 10-15 minutes. Avoid ice. Wash minor cuts with mild soap and water, apply petroleum jelly, and secure with a sterile bandage."
  }
];

export const EMERGENCY_CONTACTS: EmergencyContact[] = [
  {
    name: "National Emergency Service",
    number: "112 / 911",
    description: "Universal emergency responder for critical fire, police, or medical crises requiring instant physical dispatch."
  },
  {
    name: "Public Health Helpline",
    number: "104",
    description: "Government medical consult line providing free symptom triage advice, local healthcare directories, and non-critical guidance."
  },
  {
    name: "Disease Control & Epidemic Center",
    number: "1800-112-545",
    description: "Specialized hotline for reporting suspected vector outbreaks, infectious cases, or receiving local vaccination notifications."
  },
  {
    name: "Ambulance Triage Dispatch",
    number: "102 / 108",
    description: "Dedicated cardiac, trauma, and maternal emergency transit services equipped with standard life support."
  }
];

export const HOSPITAL_DIRECTORY: HospitalInfo[] = [
  {
    name: "City Central General Hospital",
    address: "742 Medical Center Parkway, Downtown",
    distance: "1.2 km",
    phone: "+1 (555) 019-2831",
    specialty: "24/7 Trauma Care, Cardiology, Infectious Disease Triage"
  },
  {
    name: "St. Jude Pulmonary & Asthma Care",
    address: "310 Aeration Blvd, Westside District",
    distance: "3.5 km",
    phone: "+1 (555) 014-9922",
    specialty: "Respiratory Emergencies, Allergy & Immunology, Pediatric Asthma"
  },
  {
    name: "Metro Endocrinology & Lifestyle Clinic",
    address: "15 Wellness Avenue, South Plaza",
    distance: "4.8 km",
    phone: "+1 (555) 017-4830",
    specialty: "Diabetes Management, Chronic Metabolic Diseases, Diabetic Wound Care"
  },
  {
    name: "Northside Pediatric and Community Hospital",
    address: "108 Oakwood Road, North Sector",
    distance: "6.1 km",
    phone: "+1 (555) 018-7711",
    specialty: "Pediatric Emergency, Outpatient Vaccination, Maternal Wellness"
  }
];

// Interactive Symptom Checker Logic Triage Database
export interface SymptomTriageRule {
  conditions: string[];
  riskLevel: "Low" | "Moderate" | "High";
  advice: string;
}

export const SYMPTOM_TRIAGE_DB: Record<string, SymptomTriageRule> = {
  // Combinations are matched based on selected symptom keys:
  // Keys: "fever", "cough", "headache", "shortness_of_breath", "joint_pain", "high_blood_sugar", "chest_pain", "wheezing"
  "fever,headache,joint_pain": {
    conditions: ["Dengue Fever", "Chikungunya", "Viral Infection"],
    riskLevel: "High",
    advice: "Severe joint pain and high fever can indicate Dengue. Avoid taking NSAIDs like Ibuprofen or Aspirin as they can increase bleeding risk. Take Paracetamol/Acetaminophen for fever, rest in bed, drink plenty of fluids, and visit a doctor immediately for a blood count test."
  },
  "fever,cough,headache": {
    conditions: ["Influenza (Flu)", "Common Cold", "Early COVID-19"],
    riskLevel: "Moderate",
    advice: "Monitor your body temperature and oxygen levels. Isolate at home, stay well hydrated, and rest. If breathing becomes difficult or fever persists above 102°F (38.9°C) for more than 3 days, seek medical evaluation."
  },
  "fever,cough,shortness_of_breath": {
    conditions: ["COVID-19", "Pneumonia", "Severe Respiratory Infection"],
    riskLevel: "High",
    advice: "The presence of fever and cough accompanied by shortness of breath is a major warning sign. Monitor oxygen saturation using a pulse oximeter. Seek emergency medical attention immediately if oxygen drops below 94% or you experience chest pressure."
  },
  "high_blood_sugar,headache": {
    conditions: ["Diabetes Hyperglycemia", "Diabetic Ketoacidosis risk"],
    riskLevel: "High",
    advice: "High blood glucose levels with headache indicates potential hyperglycemia. Drink plenty of water to flush out ketones. Check your blood sugar level and take insulin or medications as prescribed. If accompanied by confusion, deep rapid breathing, or fruity breath, go to an emergency room immediately."
  },
  "chest_pain,shortness_of_breath": {
    conditions: ["Myocardial Infarction (Heart Attack)", "Angina", "Pulmonary Embolism"],
    riskLevel: "High",
    advice: "EMERGENCY: Chest pain radiating to the jaw, arm, or neck accompanied by breathing difficulty requires immediate medical care. Sit upright, chew a standard adult aspirin if not allergic, call emergency services (112 / 911), and do not drive yourself to the hospital."
  },
  "cough,wheezing,shortness_of_breath": {
    conditions: ["Asthma Flare-up", "Bronchitis", "COPD Exacerbation"],
    riskLevel: "Moderate",
    advice: "Use your rescue inhaler (Albuterol/Bronchodilator) immediately as prescribed. Move to a dust-free environment with clean, warm air. Sit upright and practice pursed-lip breathing. If the inhaler fails to relieve wheezing or speaking is difficult, seek emergency care."
  },
  "fever,cough": {
    conditions: ["Viral Illness", "Mild Bronchitis", "Influenza"],
    riskLevel: "Low",
    advice: "Rest at home, drink warm broths and water, and cover your mouth. Use humidifiers if available. Monitor symptoms. If fever resolves but cough worsens or lingers over 10 days, contact a primary care provider."
  }
};

// Fallback algorithm for generic symptom combinations:
export function analyzeSymptoms(selectedKeys: string[]): SymptomTriageRule {
  if (selectedKeys.length === 0) {
    return {
      conditions: ["None detected"],
      riskLevel: "Low",
      advice: "Please select one or more symptoms to analyze your risk profile."
    };
  }

  // Look for exact combinations or subsets
  const sortedKeys = [...selectedKeys].sort().join(",");
  if (SYMPTOM_TRIAGE_DB[sortedKeys]) {
    return SYMPTOM_TRIAGE_DB[sortedKeys];
  }

  // Check if highly critical symptoms are checked
  if (selectedKeys.includes("chest_pain")) {
    return {
      conditions: ["Cardiovascular Emergency", "Angina Pectoris"],
      riskLevel: "High",
      advice: "EMERGENCY: Chest pain requires immediate medical evaluation. Do not ignore this symptom. Please contact emergency medical services (112 / 911) right away."
    };
  }

  if (selectedKeys.includes("shortness_of_breath")) {
    return {
      conditions: ["Acute Respiratory Distress", "Asthma flare-up", "Severe Covid-19/Pneumonia"],
      riskLevel: "High",
      advice: "Difficulty breathing is a serious symptom. If this is accompanied by chest pressure, coughing up blood, or bluish lips, visit the nearest emergency department immediately."
    };
  }

  if (selectedKeys.includes("fever") && selectedKeys.includes("joint_pain")) {
    return {
      conditions: ["Dengue Fever", "Chikungunya", "Influenza"],
      riskLevel: "High",
      advice: "A combination of fever and severe joint/muscle pain is characteristic of vector-borne tropical infections like Dengue. Please seek a diagnostic blood test and strictly avoid blood-thinning NSAIDs."
    };
  }

  if (selectedKeys.includes("high_blood_sugar")) {
    return {
      conditions: ["Hyperglycemia (Elevated Blood Glucose)"],
      riskLevel: "Moderate",
      advice: "An elevated blood glucose level requires careful lifestyle management or medication adjustments. Continue to check blood sugar levels, stay hydrated, and consult your physician to optimize your diabetes management plan."
    };
  }

  if (selectedKeys.includes("wheezing") || selectedKeys.includes("cough")) {
    return {
      conditions: ["Bronchial Asthma", "Respiratory Bronchitis", "Seasonal Allergies"],
      riskLevel: "Moderate",
      advice: "Wheezing or dry coughs represent bronchial hypersensitivity. Use prescribed rescue bronchodilators if available, stay away from smoky or dusty areas, and monitor your breathing capacity."
    };
  }

  // Catch-all mild symptoms
  return {
    conditions: ["General Mild Viral Infection", "Incipient Toxin Exposure"],
    riskLevel: "Low",
    advice: "Your checked symptoms suggest a low risk, likely a common cold or mild viral illness. Ensure 8 hours of sleep, double your fluid intake, and practice strict hand hygiene. If symptoms worsen over 48 hours, seek medical advice."
  };
}
