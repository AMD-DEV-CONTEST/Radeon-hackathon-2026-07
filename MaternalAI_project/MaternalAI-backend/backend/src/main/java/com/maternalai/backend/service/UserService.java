package com.maternalai.backend.service;

import java.util.List;

import org.springframework.lang.NonNull;

import com.maternalai.backend.entity.User;

public interface UserService {

   User saveUser(User user);

    List<User> getAllUsers();

    User updateUser(Long id, User user);

    void deleteUser(@NonNull Long id);

    boolean login(String email, String password);

    User getUserById(Long id);
}