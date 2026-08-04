using System.Collections;
using UnityEngine;
using UniVRM10;

public class CharacterDriver : MonoBehaviour
{
    [SerializeField] private string characterName;
    private Vrm10Instance vrmInstance;
    private Animator animator;
    [SerializeField] private RuntimeAnimatorController animatorController;
    private AudioSource audioSource;

    // Handle Visemes, LookAt and Expressions.
    private Coroutine playbackRoutine;

    // Viseme Handling
    // Viseme Handling
    private readonly string[] visemeNames = { "aa", "ee", "ih", "oh", "ou" };
    private readonly ExpressionKey[] visemeKeys =
    {
        ExpressionKey.CreateFromPreset(ExpressionPreset.aa),
        ExpressionKey.CreateFromPreset(ExpressionPreset.ee),
        ExpressionKey.CreateFromPreset(ExpressionPreset.ih),
        ExpressionKey.CreateFromPreset(ExpressionPreset.oh),
        ExpressionKey.CreateFromPreset(ExpressionPreset.ou),
    };

    // Expression Handling
    private readonly string[] expressionNames = { "neutral", "angry", "fun", "sorrow" };
    private readonly ExpressionKey[] expressionKeys =
    {
        ExpressionKey.CreateFromPreset(ExpressionPreset.neutral),
        ExpressionKey.CreateFromPreset(ExpressionPreset.angry),
        ExpressionKey.CreateFromPreset(ExpressionPreset.relaxed),
        ExpressionKey.CreateFromPreset(ExpressionPreset.sad),
    };

    private float[] targetWeights;
    private float[] currentWeights;

    [SerializeField, Range(5f, 30f)] private float lipSyncBlendSpeed = 15f;


    private float[] targetExpressionWeights;
    private float[] currentExpressionWeights;
    [SerializeField, Range(1f, 30f)] private float expressionBlendSpeed = 8f;

    // Head Turn Handling
    [SerializeField, Range(1f, 15f)] private float headTurnSpeed = 5f;
    private Transform activeLookTarget;
    private Vector3 currentLookPosition;
    private float targetLookWeight;
    private float currentLookWeight;

     public float minBlinkInterval = 2.0f;
    public float maxBlinkInterval = 5.0f;
    public float blinkSpeed = 0.05f;

    private ExpressionKey blinkKey;


    void Awake()
    {
        if (!TryGetComponent<AudioSource>(out audioSource))
        {
            Debug.LogError("Could not find Audio Source on Character!");
        }

        // Initialize Viseme Arrays
        targetWeights = new float[visemeKeys.Length];
        currentWeights = new float[visemeKeys.Length];

        // Initialize Expression Arrays
        targetExpressionWeights = new float[expressionKeys.Length];
        currentExpressionWeights = new float[expressionKeys.Length];
    }

    public void PopulateVariables()
    {
        vrmInstance = GetComponentInChildren<Vrm10Instance>();
        if (vrmInstance == null)
        {
            Debug.LogError("Could not find Vrm10Instance!");
        }

        // Set update when off screen to true
        SkinnedMeshRenderer[] allRenderers = GetComponentsInChildren<SkinnedMeshRenderer>();
        foreach (SkinnedMeshRenderer smr in allRenderers)
        {
            smr.updateWhenOffscreen = true;
        }
        Debug.Log($"Found and updated {allRenderers.Length} SkinnedMeshRenderers.");

        blinkKey = ExpressionKey.CreateFromPreset(ExpressionPreset.blink);
        StartCoroutine(BlinkRoutine());
    }


    private void Start()
    {
        ShowRunner.OnDialogueTurn += HandleDialogue;
        PopulateVariables();
    }

    void OnDestroy()
    {
        ShowRunner.OnDialogueTurn -= HandleDialogue;
       
    }

    void Update()
    {
        if (!vrmInstance) return;

        // Smoothly Blend Visemes
        float visDt = Time.deltaTime * lipSyncBlendSpeed;

        for (int i = 0; i < visemeKeys.Length; i++)
        {
            currentWeights[i] = Mathf.Lerp(currentWeights[i], targetWeights[i], visDt);
            vrmInstance.Runtime.Expression.SetWeight(visemeKeys[i], currentWeights[i]);
        }

        // Smoothly Blend Expressions
        float expDt = Time.deltaTime * expressionBlendSpeed;
        for (int i = 0; i < expressionKeys.Length; i++)
        {
            currentExpressionWeights[i] = Mathf.Lerp(currentExpressionWeights[i], targetExpressionWeights[i], expDt);
            vrmInstance.Runtime.Expression.SetWeight(expressionKeys[i], currentExpressionWeights[i]);
        }
    }

    public void HandleAnimatorIK(int layerIndex)
    {
        if (animator == null) return;

        currentLookWeight = Mathf.Lerp(currentLookWeight, targetLookWeight, Time.deltaTime * headTurnSpeed);

        if (activeLookTarget != null)
        {
            if (currentLookWeight < 0.05f)
            {
                currentLookPosition = activeLookTarget.position;
            }
            else
            {
                currentLookPosition = Vector3.Lerp(currentLookPosition, activeLookTarget.position, Time.deltaTime * headTurnSpeed);
            }
        }
        animator.SetLookAtWeight(currentLookWeight, 0.1f, 0.8f, 1.0f, 0.5f);
        animator.SetLookAtPosition(currentLookPosition);
    }

    private void HandleDialogue(Dialogue dialogue)
    {
        audioSource.clip = ShowRunner.AudioLibrary[dialogue.audioFileName];
        audioSource.Play();

        // Handle Expression
        SetTargetExpression(dialogue.expression);

        // Handle Visemes
        if (playbackRoutine != null)
        {
            StopCoroutine(playbackRoutine);
        }

        if (dialogue.visemes != null && dialogue.visemes.Count > 0)
        {
            playbackRoutine = StartCoroutine(HandlePlayback(dialogue));
        }
    }

    // Handle Visemes
    private IEnumerator HandlePlayback(Dialogue dialogue)
    {
        int visemeIndex = 0;
        bool hasVisemes = dialogue.visemes != null && dialogue.visemes.Count > 0;

        while (audioSource.isPlaying)
        {
            float currentTime = audioSource.time;
            // Handle Visemes
            if (hasVisemes)
            {
                while (visemeIndex < dialogue.visemes.Count - 1 && currentTime >= dialogue.visemes[visemeIndex + 1].start)
                {
                    visemeIndex++;
                }

                if (currentTime >= dialogue.visemes[visemeIndex].start)
                {
                    if (currentTime <= dialogue.visemes[visemeIndex].start + 0.2f)
                    {
                        SetTargetViseme(dialogue.visemes[visemeIndex].viseme);
                    }
                    else
                    {
                        SetTargetViseme("pp");
                    }
                }
            }

            yield return null;
        }
        SetTargetViseme("pp");
        // SetLookTarget("");
        // SetTargetExpression("neutral");
    }

    private void SetTargetViseme(string viseme)
    {
        for (int i = 0; i < targetWeights.Length; i++)
        {
            targetWeights[i] = 0f;
        }

        int index = System.Array.IndexOf(visemeNames, viseme.ToLower());
        if (index >= 0)
        {
            targetWeights[index] = 1f;
        }
    }


    private void SetTargetExpression(string expression)
    {
        for (int i = 0; i < targetExpressionWeights.Length; i++)
        {
            targetExpressionWeights[i] = 0f;
        }

        if (string.IsNullOrEmpty(expression))
        {
            targetExpressionWeights[0] = 1f; // Defaulting to neutral
            return;
        }
        int index = System.Array.IndexOf(expressionNames, expression.ToLower());
        if (index >= 0)
        {
            targetExpressionWeights[index] = 1f;
        }
        else
        {
            Debug.LogWarning($"Expression '{expression}' not recognized. Defaulting to neutral");
            targetExpressionWeights[0] = 1f;
        }

    }

    private IEnumerator BlinkRoutine()
    {
        if (vrmInstance == null)
        {
            yield break;
        }

        while (true)
        {
            // Wait for a random natural interval
            float waitTime = Random.Range(minBlinkInterval, maxBlinkInterval);
            yield return new WaitForSeconds(waitTime);

            // Close Eyes (Lerp to 1)
            float t = 0;
            while (t < blinkSpeed)
            {
                t += Time.deltaTime;
                float weight = Mathf.Lerp(0f, 1f, t / blinkSpeed);
                vrmInstance.Runtime.Expression.SetWeight(blinkKey, weight);
                yield return null;
            }
            vrmInstance.Runtime.Expression.SetWeight(blinkKey, 1f);

            // Keep them closed for a tiny fraction of a second
            yield return new WaitForSeconds(0.02f);

            // Open Eyes (Lerp to 0)
            t = 0;
            while (t < blinkSpeed)
            {
                t += Time.deltaTime;
                float weight = Mathf.Lerp(1f, 0f, t / blinkSpeed);
                vrmInstance.Runtime.Expression.SetWeight(blinkKey, weight);
                yield return null;
            }
            vrmInstance.Runtime.Expression.SetWeight(blinkKey, 0f);
        }
    }
}
