using System;
using System.Collections.Generic;

[Serializable]
public class LookAt
{
    public float start;
    public string character;
}

[Serializable]
public class Viseme
{
    public float start;
    public string viseme;
}

[Serializable]
public class Dialogue
{
    public string dialogue;
    public string expression;
    public List<Viseme> visemes;
    public List<LookAt> lookAt;
    public string audioFileName;
}

[Serializable]
public class EpisodePayload
{
    public List<string> headlines;
    public List<Dialogue> dialogues;
    public string therapistCostume = "";
    public string maleCostume = "";
    public string femaleCostume = "";
}