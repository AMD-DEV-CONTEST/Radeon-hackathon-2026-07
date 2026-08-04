using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Runtime.InteropServices;
using TMPro;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

[System.Serializable]
public struct PrefabMapping
{
    public string prefabName;
    public GameObject prefab;
}

public class ShowRunner : MonoBehaviour
{
    public static Dictionary<string, AudioClip> AudioLibrary = new Dictionary<string, AudioClip>();
    public static event Action<Dialogue> OnDialogueTurn;

    public NewsTicker newsTicker;


    [Header("UI Elements")]
    public TMP_InputField keywordInput;
    public Button generateButton;


    public void OnGenerateButtonClicked()
    {
        string keyword = keywordInput.text;
        if(string.IsNullOrWhiteSpace(keyword))
        {
            Debug.LogWarning("Keyword is empty! Please type something.");
            return;
        }

        generateButton.interactable = false;
        StartCoroutine(GenerateAndRunEpisodeRoutine(keyword));
    }


    private IEnumerator GenerateAndRunEpisodeRoutine(string keyword)
    {
        string generateUrl = "http://localhost:8000/generate";
        Debug.Log("Requesting new episode generation from backend... This might take a while...");

        WWWForm form  = new WWWForm();
        form.AddField("keyword", keyword);

        using (UnityWebRequest webRequest = UnityWebRequest.Post(generateUrl, form))
        {
            yield return webRequest.SendWebRequest();
            if (webRequest.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError($"Failed to generate episode: {webRequest.error}");
                yield break;
            }

            string filename = webRequest.downloadHandler.text.Trim('"', '\n', '\r');
            Debug.Log($"Generation complete! Received filename: {filename}");

            string downloadUrl = $"http://localhost:8000/episodes/{filename}";

            RunEpisode(downloadUrl);
        }

        generateButton.interactable = true;
    }

    public void RunEpisode(string url)
    {
        StartCoroutine(DownloadAndExtractZipRoutine(url));
    }
    

    private IEnumerator DownloadAndExtractZipRoutine(string url)
    {

        Debug.Log($"Download .zip file... {url}");
        using (UnityWebRequest webRequest = UnityWebRequest.Get(url))
        {
            yield return webRequest.SendWebRequest();
            if (webRequest.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError($"Failed to download: {webRequest.error}");
                yield break;
            }
            EpisodePayload currentEpisode = ProcessZipData(webRequest.downloadHandler.data);
            if (currentEpisode != null)
            {
                Debug.Log($"Loaded Episode! Found {currentEpisode.dialogues.Count} dialogues!");
                StartCoroutine(PlayEpisodeRoutine(currentEpisode));
                newsTicker.StartTicker(currentEpisode.headlines);
            }
        }
    }

    private EpisodePayload ProcessZipData(byte[] zipData)
    {
        AudioLibrary.Clear();
        EpisodePayload CurrentEpisode = null;

        using (MemoryStream zipStream = new MemoryStream(zipData))
        using (ZipArchive archive = new ZipArchive(zipStream, ZipArchiveMode.Read))
        {
            // EpisodePayload CurrentShow;
            foreach (ZipArchiveEntry entry in archive.Entries)
            {
                // Extract JSON
                if (entry.FullName.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
                {
                    using (StreamReader reader = new StreamReader(entry.Open()))
                    {
                        CurrentEpisode = JsonUtility.FromJson<EpisodePayload>(reader.ReadToEnd());
                        Debug.Log("Extracted Script Successfully!");
                    }
                }

                // Extract Raw PCM (.bin)
                else if (entry.FullName.EndsWith(".bin", StringComparison.OrdinalIgnoreCase))
                {
                    using (MemoryStream ms = new MemoryStream())
                    {
                        entry.Open().CopyTo(ms);
                        byte[] rawBytes = ms.ToArray();

                        int sampleCount = rawBytes.Length / 4;
                        float[] audioFloats = new float[sampleCount];

                        Buffer.BlockCopy(rawBytes, 0, audioFloats, 0, rawBytes.Length);
                        AudioClip clip = AudioClip.Create(entry.Name, sampleCount, 1, 24000, false);
                        clip.SetData(audioFloats, 0);
                        AudioLibrary.Add(entry.Name, clip);
                    }
                }
            }

        }
        return CurrentEpisode;
    }


    private IEnumerator PlayEpisodeRoutine(EpisodePayload episodePayload)
    {
        Debug.Log("Starting Episode Playback...");

        foreach (Dialogue turn in episodePayload.dialogues)
        {
            if (AudioLibrary.TryGetValue(turn.audioFileName, out AudioClip clip))
            {
                OnDialogueTurn?.Invoke(turn);
                yield return new WaitForSeconds(clip.length);
                yield return new WaitForSeconds(0.3f);
            }
            else
            {
                Debug.LogError($"Audio clip {turn.audioFileName} missing from Zip!");
            }
        }
        Debug.Log("Episode Finished!");
    }


}
